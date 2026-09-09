"""Arranca la demostración local sin cargar ni borrar cuentas."""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.load_all import DEFAULTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--banks-only', action='store_true', help='Conservar ASFI y BCB ya iniciados')
    parser.add_argument('--panel-port', type=int, default=8200)
    args = parser.parse_args()
    logdir = ROOT / 'data' / 'service-logs'
    logdir.mkdir(parents=True, exist_ok=True)
    children = []
    logs = []

    def stop(*_, code=0):
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
        raise SystemExit(code)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with httpx.Client(timeout=2, trust_env=False) as client:
        def start(name, app, appdir, port, env, health, expected_bank=None):
            try:
                response = client.get(health)
                response.raise_for_status()
                if expected_bank is not None and response.json().get('bank_id') != expected_bank:
                    raise RuntimeError(f'El puerto {port} está ocupado por otro servicio')
                print(f'{name}: ya disponible', flush=True)
                return
            except httpx.RequestError:
                pass
            log = (logdir / f'{name}.log').open('a')
            logs.append(log)
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', app, '--app-dir', str(ROOT / appdir),
                                        '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT,
                                       env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT)
            children.append(process)
            return name, process, health, expected_bank

        waiting = []
        try:
            for bank, (store, default_url) in sorted(DEFAULTS.items()):
                storage = {'PostgreSQLStore':'postgres', 'MySQLStore':'mysql', 'SQLiteStore':'sqlite',
                           'MongoStore':'mongo', 'RedisStore':'redis', 'Neo4jStore':'neo4j'}[store.__name__]
                item = start(f'bank_{bank:02d}', 'bank_template.main:app', 'banks-services', 8100 + bank,
                             {'BANK_ID':str(bank), 'BANK_STORAGE':storage,
                              'DATABASE_URL':os.getenv(f'BANK_{bank:02d}_DATABASE_URL', default_url)},
                             f'http://127.0.0.1:{8100+bank}/health', bank)
                if item:
                    waiting.append(item)
            if not args.banks_only:
                for item in (
                    start('bcb', 'main:app', 'bcb-service', 8001, {'BCB_UPDATE_INTERVAL':os.getenv('BCB_UPDATE_INTERVAL','1')},
                          'http://127.0.0.1:8001/health'),
                    start('asfi', 'main:app', 'asfi-service', args.panel_port, {},
                          f'http://127.0.0.1:{args.panel_port}/api/panel/estado'),
                ):
                    if item:
                        waiting.append(item)
            deadline = time.monotonic() + 40
            while waiting and time.monotonic() < deadline:
                for item in waiting[:]:
                    name, process, health, bank = item
                    if process.poll() is not None:
                        raise RuntimeError(f'{name} no pudo iniciar. Revisa {logdir/name}.log')
                    try:
                        response = client.get(health)
                        response.raise_for_status()
                        if bank is not None and response.json().get('bank_id') != bank:
                            raise RuntimeError(f'{name}: identidad incorrecta')
                        print(f'{name}: disponible', flush=True)
                        waiting.remove(item)
                    except httpx.HTTPError:
                        pass
                if waiting:
                    time.sleep(.3)
            if waiting:
                raise RuntimeError('Servicios sin respuesta: ' + ', '.join(item[0] for item in waiting))
            print(f'Listo: http://127.0.0.1:{args.panel_port}/panel — Ctrl+C para detener los procesos iniciados aquí.', flush=True)
            while True:
                for process in children:
                    if process.poll() is not None:
                        raise RuntimeError('Un servicio terminó; revisa data/service-logs')
                time.sleep(1)
        except Exception as exc:
            print(str(exc), file=sys.stderr, flush=True)
            stop(code=1)


if __name__ == '__main__':
    main()
