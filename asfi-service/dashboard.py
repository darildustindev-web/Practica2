"""Panel local de presentación, servido por ASFI sin dependencias de frontend."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote

import httpx
from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from monitor import monitor
from shared.money import parse_money, convert_money


class Interval(BaseModel):
    segundos: int = Field(ge=1, le=86400)


def read_consolidation(url, bank=None, ref=None):
    """Lectura independiente; abrir el panel nunca inicializa ni limpia una BD."""
    postgres = url.startswith(('postgresql://', 'postgres://'))
    if postgres:
        import psycopg2
        db = psycopg2.connect(url, connect_timeout=3)
        db.set_session(readonly=True)
        mark = '%s'
    else:
        import sqlite3
        path = Path(url[10:])
        if not path.exists():
            return []
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        mark = '?'
    try:
        cur = db.cursor()
        sql = 'SELECT banco_id,cuenta_id,saldo_usd,saldo_bs,tipo_cambio,codigo_verificacion,fecha_conversion,estado FROM asfi_cuentas'
        params = ()
        if bank is not None:
            sql += ' WHERE banco_id=' + mark + ' AND cuenta_id=' + mark
            params = (bank, ref)
        sql += ' ORDER BY fecha_conversion DESC LIMIT 30'
        cur.execute(sql, params)
        keys = ('banco_id','cuenta_id','saldo_usd','saldo_bs','tipo_cambio','codigo_verificacion','timestamp','estado')
        return [dict(zip(keys, [row[0], *[str(v) if v is not None else None for v in row[1:]]])) for row in cur.fetchall()]
    finally:
        db.close()


async def probe_services(urls, rate_url):
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        async def check(bank, base):
            try:
                response = await client.get(base + '/cuentas/cifradas', params={'limit': 1})
                response.raise_for_status()
                data = response.json()
                if data.get('banco_id') != bank or not isinstance(data.get('cuentas'), list):
                    raise ValueError('Respuesta o identidad incorrecta')
                return {'banco_id': bank, 'disponible': True, 'total': data.get('total')}
            except (httpx.HTTPError, ValueError):
                return {'banco_id': bank, 'disponible': False, 'detalle': 'API sin conexión o base de datos no disponible'}
        banks = await asyncio.gather(*(check(bank, base) for bank, base in urls.items()))
        try:
            response = await client.get(rate_url)
            response.raise_for_status()
            parse_money(response.json().get('tipo_cambio'), rate=True)
            bcb_ready = True
        except (httpx.HTTPError, ValueError):
            bcb_ready = False
    return {'listo': bool(banks) and all(b['disponible'] for b in banks) and bcb_ready,
            'bcb': bcb_ready, 'bancos': banks}


def install_dashboard(app, execute, bcb_url, database_url, bank_urls):
    static = Path(__file__).parent / 'static'
    app.mount('/panel/assets', StaticFiles(directory=static), name='panel-assets')
    task = None

    def same_origin(request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'La acción debe iniciarse desde este panel')

    async def bcb(method, *, interval=None):
        target = bcb_url()
        if interval is not None:
            parsed = urlsplit(target)
            target = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rsplit('/', 1)[0] + '/configurar-intervalo', '', ''))
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.request(method, target, params={'segundos': interval} if interval is not None else None)
                response.raise_for_status()
                data = response.json()
                if interval is None:
                    data['tipo_cambio_formateado'] = format(parse_money(data.get('tipo_cambio_formateado', data.get('tipo_cambio')), rate=True), 'f')
                return data
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, 'BCB no disponible o respuesta inválida. Comprueba que esté encendido.') from exc

    @app.get('/panel', include_in_schema=False)
    async def panel():
        return FileResponse(static / 'index.html')

    @app.get('/api/panel/estado')
    async def state():
        return monitor.snapshot()

    @app.get('/api/panel/cotizacion')
    async def rate():
        return await bcb('GET')

    @app.put('/api/panel/intervalo')
    async def interval(value: Interval, request: Request):
        same_origin(request)
        return await bcb('PUT', interval=value.segundos)

    @app.get('/api/panel/servicios')
    async def services():
        return await probe_services(bank_urls(), bcb_url())

    @app.post('/api/panel/ejecutar', status_code=202)
    async def start(request: Request):
        nonlocal task
        same_origin(request)
        if monitor.running or (task is not None and not task.done()):
            raise HTTPException(409, 'Ya hay un barrido en ejecución')
        availability = await probe_services(bank_urls(), bcb_url())
        if not availability['listo']:
            missing = [str(b['banco_id']) for b in availability['bancos'] if not b['disponible']]
            detail = 'No se inició el barrido. '
            if missing:
                detail += 'APIs bancarias no disponibles: ' + ', '.join(missing) + '. '
            if not availability['bcb']:
                detail += 'BCB no disponible. '
            detail += 'Inicia los servicios con: .venv/bin/python scripts/run_panel.py'
            raise HTTPException(503, detail)
        if monitor.running or (task is not None and not task.done()):
            raise HTTPException(409, 'Ya hay un barrido en ejecución')
        async def run():
            try:
                await execute()
            except Exception:
                # execute registra el fallo en monitor; se presenta al usuario.
                pass
        task = asyncio.create_task(run())
        return {'status': 'INICIANDO'}

    @app.get('/api/panel/consolidadas')
    async def consolidated():
        try:
            return {'cuentas': await asyncio.to_thread(read_consolidation, database_url())}
        except Exception as exc:
            raise HTTPException(503, 'Consolidación no disponible. Ejecuta el primer barrido o comprueba la base ASFI.') from exc

    @app.get('/api/panel/verificar')
    async def verify(banco: int = Query(ge=1, le=14), cuenta: str = Query(min_length=1, max_length=255)):
        try:
            rows = await asyncio.to_thread(read_consolidation, database_url(), banco, cuenta)
            if not rows:
                raise HTTPException(404, 'Cuenta no consolidada en ASFI')
            central = rows[0]
            base = bank_urls().get(banco)
            if not base:
                raise HTTPException(404, 'Banco no activo')
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(base + '/cuentas/' + quote(cuenta, safe=''))
                response.raise_for_status()
                account = response.json()['cuenta']
            bank = {'saldo_bs': account.get('SaldoBs'), 'tipo_cambio': account.get('TipoCambio'),
                    'codigo_verificacion': account.get('CodigoVerificacion')}
            checks = {
                'saldo': parse_money(bank['saldo_bs']) == parse_money(central['saldo_bs']),
                'tasa': parse_money(bank['tipo_cambio']) == parse_money(central['tipo_cambio']),
                'codigo': bank['codigo_verificacion'] == central['codigo_verificacion'],
                'calculo': convert_money(central['saldo_usd'], central['tipo_cambio']) == parse_money(central['saldo_bs']),
                'confirmada': central['estado'] == 'CONFIRMADA',
            }
            return {'coincide': all(checks.values()), 'verificaciones': checks, 'asfi': central, 'banco': bank}
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, 'No se pudo verificar la cuenta contra el banco. Comprueba su conexión y estado.') from exc
