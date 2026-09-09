"""Carga JSONL incremental, con cuarentena y métricas por motor."""
from datetime import datetime, timezone
import uuid
import argparse
import json
from pathlib import Path
from time import perf_counter
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.portable import bloquear, COMPARTIDO

FIELDS = ('Nro','IdBanco','Identificacion','Nombres','Apellidos','NroCuenta','Saldo')


def _load(source, store, batch_size=1000, expected_bank=None):
    if not 1 <= batch_size <= 1000:
        raise ValueError('batch-size debe estar entre 1 y 1000')
    started=perf_counter()
    stats=dict(ejecucion_id=uuid.uuid4().hex,inicio=datetime.now(timezone.utc).isoformat(),leidas=0,cargadas=0,rechazadas=0)
    batch=[]
    source=Path(source)
    with source.open(encoding='utf-8',errors='replace') as lines, source.with_suffix('.load-rejected.jsonl').open('w',encoding='utf-8') as rejected:
        def reject(n,reason):
            stats['rechazadas']+=1
            rejected.write(json.dumps(dict(linea=n,motivo=str(reason),banco_id=expected_bank,fecha_utc=datetime.now(timezone.utc).isoformat(),ejecucion_id=stats['ejecucion_id']),ensure_ascii=False)+'\n')
        def flush():
            # Los errores de infraestructura se propagan: no descartar miles de
            # filas sanas si una BD se desconecta. La recarga es insert-only.
            def insert(records):
                try:
                    store.upsert_accounts_batch([r for _,r in records])
                    stats['cargadas']+=len(records)
                except Exception as exc:
                    # Sólo fallos de datos se aíslan. Fallos de conectividad o
                    # programación detienen el cargador de forma controlada.
                    if type(exc).__name__ not in {'DataError','IntegrityError'}:
                        raise
                    if len(records)==1:
                        reject(records[0][0],f'Base de datos: {type(exc).__name__}')
                    else:
                        middle=len(records)//2
                        insert(records[:middle]);insert(records[middle:])
            insert(batch)
            batch.clear()
        def bounded_lines():
            while True:
                line=lines.readline(524289)
                if not line:break
                if len(line)>524288:
                    while line and not line.endswith('\n'):
                        line=lines.readline(524289)
                    yield None
                else:
                    yield line
        for number,line in enumerate(bounded_lines(),1):
            if line is None:
                stats['leidas']+=1
                reject(number,'Fila JSONL excede 512 KiB')
                continue
            if not line.strip():
                continue
            stats['leidas']+=1
            try:
                row=json.loads(line)
                if not isinstance(row,dict) or any(k not in row for k in FIELDS):
                    raise ValueError('Registro incompleto')
                if not str(row['Nro']).isascii() or not str(row['Nro']).isdigit() or not 0<int(row['Nro'])<=9223372036854775807:
                    raise ValueError('Nro inválido')
                row['Nro']=str(int(row['Nro']))
                if str(row['IdBanco']) not in {str(i) for i in range(1,15)}:
                    raise ValueError('IdBanco debe ser entero de 1 a 14')
                bank=int(row['IdBanco'])
                if bank not in range(1,15) or (expected_bank and bank!=expected_bank):
                    raise ValueError('Banco incorrecto')
                if any(not isinstance(row[k],str) or not row[k] or '\ufffd' in row[k] or '\x00' in row[k] or len(row[k].encode('utf-8'))>60000 for k in FIELDS[2:]):
                    raise ValueError('Campo cifrado inválido')
                batch.append((number,row))
            except (ValueError,TypeError) as exc:
                reject(number,exc)
                continue
            if len(batch)>=batch_size:
                flush()
        if batch:
            flush()
    stats['segundos']=round(perf_counter()-started,4)
    stats['registros_por_segundo']=round(stats['cargadas']/max(stats['segundos'],0.0001),2)
    return stats


def load(source, store, batch_size=1000, expected_bank=None):
    with (Path(source).parent/'.seed.lock').open('a') as lock:
        try:
            bloquear(lock, COMPARTIDO, bloqueante=False)
        except BlockingIOError as exc:
            raise ValueError('El seeder está publicando este dataset; reintente al finalizar') from exc
        return _load(source,store,batch_size,expected_bank)


def cli(store_class):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--database-url',required=True)
    parser.add_argument('--batch-size',type=int,default=1000)
    parser.add_argument('--bank-id',type=int)
    args=parser.parse_args()
    bank=args.bank_id
    if bank is None and args.source.stem.startswith('bank_'):
        bank=int(args.source.stem[5:])
    try:
        store=store_class(args.database_url)
        try:
            print(json.dumps(load(args.source,store,args.batch_size,bank),indent=2))
        finally:
            if hasattr(store,'close'):
                store.close()
    except Exception as exc:
        parser.exit(1,f'Carga detenida; puede reintentarse sin borrar confirmaciones: {type(exc).__name__}: {exc}\n')
