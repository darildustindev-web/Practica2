"""Carga CSV por lotes acotados; cuarentena de errores y cifrado multiproceso."""
from __future__ import annotations
from datetime import datetime, timezone
import uuid
import argparse
import csv
import json
import os
import sqlite3
import sys
import tempfile
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'asfi-service'))
from shared.money import parse_money
from crypto.ciphers import ECCCipher
from crypto.key_manager import CipherFactory

COLUMNS = ('Nro', 'Identificacion', 'Nombres', 'Apellidos', 'NroCuenta', 'IdBanco', 'Saldo')
REQUIRED_COLUMNS = set(COLUMNS)
SENSITIVE_COLUMNS = COLUMNS[1:5] + ('Saldo',)
OFFICIAL_1PCT_DISTRIBUTION: dict[int, int] = {
    1: 22472,
    2: 19975,
    3: 14981,
    4: 13983,
    5: 10487,
    6: 9488,
    7: 8489,
    8: 7491,
    9: 5493,
    10: 3496,
    11: 3995,
    12: 2247,
    13: 999,
    14: 200,
}

@dataclass
class LoadResult:
    valid_rows: list = field(default_factory=list)
    rejected_rows: list = field(default_factory=list)
    total_read: int = 0


def normalize_saldo(value):
    return format(parse_money(value), 'f')


def parse_saldo(value):
    try:
        return parse_money(value)
    except ValueError:
        return None


def normalize_row(row):
    return {str(k).strip(): str(v or '').strip() for k, v in row.items() if k is not None}


def validate_row(row, seen_nro):
    for column in COLUMNS:
        value = row.get(column, '')
        if not value:
            return f'Campo obligatorio vacío: {column}'
        if len(value) > 1024 or any(ord(c) < 32 for c in value) or '\ufffd' in value:
            return f'Campo demasiado largo, con controles o codificación inválida: {column}'
    if not row['Nro'].isascii() or not row['Nro'].isdigit() or not 0 < int(row['Nro']) <= 9223372036854775807:
        return 'Nro debe ser entero positivo BIGINT'
    if row['Nro'] in seen_nro:
        return 'Nro duplicado'
    if row['IdBanco'] not in {str(i) for i in range(1,15)}:
        return 'IdBanco fuera de 1..14'
    try:
        parse_money(row['Saldo'])
    except ValueError as exc:
        return str(exc)
    return None


def iter_rows(dataset, limit=None):
    # Deduplicación en disco: la RAM no crece con el número de cuentas.
    with tempfile.TemporaryDirectory(prefix='asfi-validation-') as temp, \
            sqlite3.connect(str(Path(temp)/'seen.sqlite')) as db, \
            Path(dataset).open(encoding='utf-8-sig', errors='replace', newline='') as source:
        db.execute('CREATE TABLE seen (nro TEXT PRIMARY KEY)')
        header = source.readline(32769)
        columns = [c.strip() for c in next(csv.reader([header], strict=True))]
        if len(header) > 32768 or len(set(columns)) != len(columns) or not REQUIRED_COLUMNS <= set(columns):
            raise ValueError('Cabecera inválida: columnas requeridas ausentes o duplicadas')
        number = 1
        while limit is None or number - 1 < limit:
            line = source.readline(32769)
            if not line:
                break
            number += 1
            row = {}
            try:
                if len(line) > 32768:
                    while line and not line.endswith('\n'):
                        line = source.readline(32769)
                    raise ValueError('Fila excede 32 KiB')
                values = next(csv.reader([line], strict=True))
                if len(values) != len(columns):
                    raise ValueError('Número de columnas incorrecto')
                row = normalize_row(dict(zip(columns, values)))
                reason = validate_row(row, ())
                if reason:
                    raise ValueError(reason)
                row['Nro'] = str(int(row['Nro']))
                row['Saldo'] = normalize_saldo(row['Saldo'])
                try:
                    db.execute('INSERT INTO seen VALUES (?)', (row['Nro'],))
                except sqlite3.IntegrityError:
                    raise ValueError('Nro duplicado')
                if number % 1000 == 0:
                    db.commit()
                yield number, row, None
            except (ValueError, csv.Error, StopIteration) as exc:
                yield number, row, str(exc) or 'Fila vacía'


def load_rows(dataset, limit=None):
    """Compatibilidad para muestras pequeñas; CLI utiliza iter_rows."""
    result = LoadResult()
    for number, row, error in iter_rows(dataset, limit):
        result.total_read += 1
        if error:
            result.rejected_rows.append(dict(row, _linea=number, _motivo_rechazo=error))
        else:
            result.valid_rows.append(row)
    return result


_STRATEGIES = {}

def encrypt_row(row, cipher, key):
    record = dict(row)
    for column in SENSITIVE_COLUMNS:
        record[column] = cipher.encrypt(row[column], key)
    record['IdBanco'] = int(row['IdBanco'])
    return record


def encrypt_batch(batch):
    output = []
    for number, row in batch:
        try:
            bank = int(row['IdBanco'])
            if bank not in _STRATEGIES:
                cipher, key = CipherFactory.get_cipher_for_bank(bank)
                _STRATEGIES[bank] = cipher, key.public_key() if isinstance(cipher, ECCCipher) else key
            record = encrypt_row(row, *_STRATEGIES[bank])
            output.append((number, record, None))
        except Exception as exc:
            output.append((number, row, f'Cifrado: {type(exc).__name__}: {exc}'))
    return output


def _seed(dataset, output_dir, *, workers=2, batch_size=500, limit=None, target_distribution='none', seed_value=42):
    if not 1 <= workers <= 32 or not 1 <= batch_size <= 1000 or (limit is not None and limit < 0):
        raise ValueError('workers: 1..32; batch-size: 1..1000; limit no negativo')
    started = perf_counter()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Crear las claves antes de lanzar procesos evita carreras en su creación.
    for bank in (11,13):
        CipherFactory.get_cipher_for_bank(bank)
    metrics = dict(ejecucion_id=uuid.uuid4().hex, inicio=datetime.now(timezone.utc).isoformat(), leidas=0, cifradas=0, rechazadas=0, omitidas_cuota=0, workers=workers, batch_size=batch_size,
                   bancos={str(i):0 for i in range(1,15)})
    with tempfile.TemporaryDirectory(prefix='.seed-', dir=output_dir) as tmp, ExitStack() as stack:
        stage = Path(tmp)
        files = {i: stack.enter_context((stage/f'bank_{i:02d}.jsonl').open('w', encoding='utf-8')) for i in range(1,15)}
        rejected = stack.enter_context((stage/'rejected_rows.csv').open('w', encoding='utf-8', newline=''))
        report = csv.writer(rejected)
        report.writerow(['linea', 'Nro', 'IdBanco', 'motivo', 'fecha_utc', 'ejecucion_id'])
        executor = stack.enter_context(ProcessPoolExecutor(max_workers=workers)) if workers > 1 else None
        pending = deque()
        def consume(output):
            for number, record, error in output:
                if error:
                    report.writerow([number, record.get('Nro',''), record.get('IdBanco',''), error, datetime.now(timezone.utc).isoformat(), metrics['ejecucion_id']])
                    metrics['rechazadas'] += 1
                else:
                    bank = int(record['IdBanco'])
                    files[bank].write(json.dumps(record, ensure_ascii=False)+'\n')
                    metrics['cifradas'] += 1
                    metrics['bancos'][str(bank)] += 1
        def batches():
            batch = []
            # Muestreo reproducible en disco cuando se requiere la cuota oficial.
            db = stack.enter_context(sqlite3.connect(str(stage/'sample.sqlite')))
            db.execute('CREATE TABLE sample (bank INT, rank REAL, line INT, payload TEXT)')
            import random
            rng = random.Random(seed_value)
            for number, row, error in iter_rows(dataset, limit):
                metrics['leidas'] += 1
                if error:
                    report.writerow([number, row.get('Nro',''),row.get('IdBanco',''),error, datetime.now(timezone.utc).isoformat(), metrics['ejecucion_id']])
                    metrics['rechazadas'] += 1
                    continue
                if target_distribution == 'official_1pct':
                    db.execute('INSERT INTO sample VALUES (?,?,?,?)', (int(row['IdBanco']),rng.random(),number,json.dumps(row)))
                else:
                    batch.append((number,row))
                    if len(batch) == batch_size:
                        yield batch
                        batch = []
            if target_distribution == 'official_1pct':
                db.execute('CREATE INDEX selection ON sample(bank,rank)')
                selected = 0
                for bank, quota in OFFICIAL_1PCT_DISTRIBUTION.items():
                    for number, payload in db.execute('SELECT line,payload FROM sample WHERE bank=? ORDER BY rank LIMIT ?', (bank,quota)):
                        batch.append((number,json.loads(payload)))
                        selected += 1
                        if len(batch) == batch_size:
                            yield batch
                            batch = []
                metrics['omitidas_cuota'] = metrics['leidas'] - metrics['rechazadas'] - selected
            if batch:
                yield batch
        for batch in batches():
            if executor:
                pending.append(executor.submit(encrypt_batch,batch))
                if len(pending) >= workers * 2:
                    consume(pending.popleft().result())
            else:
                consume(encrypt_batch(batch))
        while pending:
            consume(pending.popleft().result())
        for f in [*files.values(),rejected]:
            f.flush()
            os.fsync(f.fileno())
        import resource
        metrics['memoria_principal_max_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
        metrics['segundos'] = round(perf_counter()-started,4)
        metrics['registros_por_segundo'] = round(metrics['leidas']/max(metrics['segundos'],0.0001),2)
        (stage/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
        for name in [*(f'bank_{i:02d}.jsonl' for i in range(1,15)), 'rejected_rows.csv', 'metrics.json']:
            os.replace(stage/name, output_dir/name)
    return metrics


def seed(dataset, output_dir, **kwargs):
    import fcntl
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    with (output_dir/'.seed.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Otra carga está usando el directorio de salida') from exc
        return _seed(dataset,output_dir,**kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--output-dir',type=Path,default=Path('data/seed'))
    parser.add_argument('--workers',type=int,default=min(4,os.cpu_count() or 1))
    parser.add_argument('--batch-size',type=int,default=500)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--target-distribution',choices=['none','official_1pct'],default='none')
    parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args()
    try:
        metrics=seed(args.dataset,args.output_dir,workers=args.workers,batch_size=args.batch_size,limit=args.limit,
                     target_distribution=args.target_distribution,seed_value=args.seed)
    except (OSError,ValueError,csv.Error) as exc:
        parser.exit(1,f'Carga detenida de forma controlada: {exc}\n')
    print(json.dumps(metrics,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
