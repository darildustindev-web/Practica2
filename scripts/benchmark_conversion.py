"""Benchmark aislado: 14 bancos SQLite temporales, APIs ASGI y ASFI real.

No mide latencia de red ni sustituye pruebas de los motores Docker.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'asfi-service'),str(ROOT/'banks-services'),str(ROOT)]
import main as asfi
from common.sqlite_store import SQLiteStore
from common.bank_router import create_bank_router
from scripts.load_common import load
from fastapi import FastAPI
import httpx


async def benchmark(source,workers,output):
    # ignore_cleanup_errors: la ASFI deja su propia conexión a asfi.sqlite abierta
    # y en Windows eso impide borrar la carpeta temporal. No invalida la medición.
    with tempfile.TemporaryDirectory(prefix='asfi-benchmark-', ignore_cleanup_errors=True) as temporary:
        temp=Path(temporary);stores=[];transports={};load_start=perf_counter()
        for bank in range(1,15):
            store=SQLiteStore('sqlite:///'+str(temp/f'bank{bank}.sqlite'))
            stores.append(store)
            load(source/f'bank_{bank:02d}.jsonl',store,1000,bank)
            app=FastAPI();app.include_router(create_bank_router(store,bank))
            transports[f'bank{bank}']=httpx.ASGITransport(app=app)
            os.environ[f'BANK_URL_{bank}']=f'http://bank{bank}/api/banco'
        load_seconds=perf_counter()-load_start
        os.environ['ASFI_CRYPTO_WORKERS']=str(workers)
        os.environ['ACTIVE_BANK_IDS']=','.join(map(str,range(1,15)))
        os.environ['ASFI_BATCH_SIZE']='500'
        asfi.DATABASE_URL='sqlite:///'+str(temp/'asfi.sqlite')
        asfi.AUDIT_FILE=temp/'audit.jsonl'
        asfi.BCB_URL='http://bcb/rate'
        async def route(request):
            if request.url.host=='bcb':
                from datetime import datetime,timezone
                rate='6.9600' if int(perf_counter())%2 else '7.0000'
                return httpx.Response(200,json=dict(tipo_cambio=rate,timestamp=datetime.now(timezone.utc).isoformat(),intervalo_actual_segundos=1))
            return await transports[request.url.host].handle_async_request(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            result=await asfi.execute_conversion(client)
            retry=await asfi.execute_conversion(client)
        for store in stores:store._connection.close()
        result=dict(carga_sqlite_segundos=round(load_seconds,4),conversion=result,reintento=retry,
                    alcance='14 bancos SQLite temporales, transporte ASGI en proceso; no mide red ni motores Docker')
        output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        if result['conversion']['errores'] or result['reintento']['errores']:
            raise SystemExit(1)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--output',type=Path,default=Path('/tmp/asfi-conversion-benchmark.json'))
    args=parser.parse_args()
    asyncio.run(benchmark(args.source_dir,args.workers,args.output))
