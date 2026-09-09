"""Demostración ASFI en terminal; consultas de sólo lectura por defecto."""
import argparse
import collections
import json
import sys
import time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]


def errors(path, banks, run_id=None):
    counts=collections.Counter(); latest={}
    if not path.exists():
        print('Todavía no existe auditoría.');return
    with path.open() as source:
        for line in source:
            try:r=json.loads(line)
            except ValueError:continue
            if run_id and r.get('barrido_id')!=run_id:continue
            bank=r.get('banco_id')
            if banks and bank not in banks:continue
            if r.get('detail'):
                key=(bank,r['detail']);counts[key]+=1;latest[key]=r.get('cuenta_id','—')
    print('Historial acumulado: incluye errores de barridos anteriores, aunque ya estén resueltos.')
    for (bank,detail),count in counts.most_common():
        print(f'Banco {bank}: {count} eventos | última cuenta {latest[(bank,detail)]} | {detail}')
    if not counts:print('Sin errores registrados para esta selección.')


def summary(state):
    print(f"\n{'EN CURSO' if state['en_ejecucion'] else 'DETENIDO'} | {state['segundos']:.2f} s")
    print('Barrido:',state.get('barrido_id') or 'sin identificador')
    print('Banco    Leídas Confirmadas    Previas    Errores   Tiempo')
    for b in state['bancos']:
        print(f"{b['banco_id']:5} {b['leidas']:9} {b['confirmadas']:11} {b['ya_confirmadas']:10} {b['errores']:10} {b.get('segundos',0):8.2f}s")
        if b.get('error_banco'):print('  '+b['error_banco'])
    for r in state.get('recientes',[]):
        if r.get('detail'):print(f"  Banco {r['banco_id']} cuenta {r.get('cuenta_id','—')}: {r['detail']}")
    if state.get('error'):print(state['error'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8200')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('estado')
    check=sub.add_parser('validar-cifrados');check.add_argument('--directorio',type=Path,default=ROOT/'data/seed-terminal');check.add_argument('--bancos',type=int,nargs='+',default=[4,5])
    e=sub.add_parser('errores');e.add_argument('--barrido');e.add_argument('--bancos',type=int,nargs='+');e.add_argument('--archivo',type=Path,default=ROOT/'data/audit.jsonl')
    i=sub.add_parser('intervalo');i.add_argument('segundos',type=int,choices=range(1,86401),metavar='SEGUNDOS')
    run=sub.add_parser('ejecutar',help='Actualiza saldos, tasas y códigos en banco y ASFI');run.add_argument('--barridos',type=int,default=1)
    v=sub.add_parser('verificar');v.add_argument('banco',type=int);v.add_argument('cuenta')
    args=parser.parse_args()
    if args.command=='errores':errors(args.archivo,args.bancos,args.barrido);return
    if args.command=='validar-cifrados':
        sys.path[:0]=[str(ROOT),str(ROOT/'asfi-service')]
        from crypto.key_manager import CipherFactory
        from shared.money import parse_money
        failures=0
        for bank in args.bancos:
            cipher,key=CipherFactory.get_cipher_for_bank(bank);count=0;bad=collections.Counter()
            with (args.directorio/f'bank_{bank:02d}.jsonl').open() as source:
                for line in source:
                    count+=1
                    try:
                        row=json.loads(line)
                        for field in ('Identificacion','Nombres','Apellidos','NroCuenta','Saldo'):
                            plain=cipher.decrypt(row[field],key)
                            if field=='Saldo':parse_money(plain)
                    except Exception as exc:bad[f'{type(exc).__name__}: {exc}']+=1
            failures+=sum(bad.values())
            print(f'Banco {bank}: {count} leídos, {sum(bad.values())} errores de descifrado/saldo')
            for reason,n in bad.items():print(f'  {n}: {reason}')
        return int(failures>0)
    with httpx.Client(base_url=args.url,timeout=30) as client:
        def api(method,path,**kwargs):
            r=client.request(method,'/api/panel/'+path,**kwargs);r.raise_for_status();return r.json()
        if args.command=='estado':summary(api('GET','estado'))
        elif args.command=='intervalo':print(json.dumps(api('PUT','intervalo',json={'segundos':args.segundos}),ensure_ascii=False))
        elif args.command=='verificar':
            data=api('GET','verificar',params={'banco':args.banco,'cuenta':args.cuenta})
            print('COINCIDE' if data['coincide'] else 'DIFERENCIAS DETECTADAS')
            for name in ('asfi','banco'):
                row=data[name];print(f"{name.upper()}: Bs {row['saldo_bs']} | tasa {row['tipo_cambio']} | código {row['codigo_verificacion']}")
            print(json.dumps(data['verificaciones'],ensure_ascii=False))
            if not data['coincide']:return 1
        elif args.command=='ejecutar':
            if args.barridos<1:parser.error('--barridos debe ser positivo')
            for number in range(args.barridos):
                print(f'Iniciando barrido {number+1}/{args.barridos}',flush=True)
                api('POST','ejecutar')
                started=time.monotonic()
                while True:
                    time.sleep(1)
                    state=api('GET','estado')
                    print(f"  {time.monotonic()-started:.0f}s | {state['totales']}",flush=True)
                    if not state['en_ejecucion']:break
                summary(state)
                if state.get('error') or state['totales']['errores']:
                    print('Se detienen los siguientes barridos; revisa los errores.');return 1
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except httpx.HTTPError as exc:
        detail=exc.response.text if isinstance(exc,httpx.HTTPStatusError) else str(exc)
        print('No se pudo completar la operación: '+detail,file=sys.stderr);sys.exit(1)
    except KeyboardInterrupt:
        print('\nConsulta detenida. Un barrido ya iniciado continúa en el servidor.');sys.exit(130)
