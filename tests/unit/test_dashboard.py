"""Pruebas del panel con transportes y bases temporales; sin conversiones reales."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent))
from test_pipeline import asfi, encrypted, confirmation
from common.sqlite_store import SQLiteStore
from common.bank_router import create_bank_router, ConfirmationRequest
from fastapi import FastAPI
from dashboard import install_dashboard, read_consolidation
from journal import Journal
from monitor import Monitor, monitor
import httpx


class DashboardTests(unittest.TestCase):
    def test_monitor_is_bounded_and_omits_personal_data(self):
        tracker = Monitor()
        tracker.begin()
        rows = [dict(cuenta_id=str(i), datos={'Nombres': 'Privado'}, estado='CONFIRMADA') for i in range(200)]
        tracker.bank(dict(banco_id=3, leidas=200, confirmadas=200), 'Completado', rows)
        tracker.end(result={'status': 'PROCESADO'})
        snapshot = tracker.snapshot()
        self.assertEqual(len(snapshot['recientes']), 80)
        self.assertNotIn('datos', snapshot['recientes'][0])
        self.assertEqual(snapshot['totales']['confirmadas'], 200)
        self.assertFalse(snapshot['en_ejecucion'])

    def test_empty_read_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.sqlite'
            self.assertEqual(read_consolidation('sqlite:///' + str(path)), [])
            self.assertFalse(path.exists())

    def test_panel_and_background_start(self):
        async def run():
            event = asyncio.Event()
            calls = []
            async def execute():
                calls.append(True)
                await event.wait()
            app = FastAPI()
            install_dashboard(app, execute, lambda: 'http://bcb/rate', lambda: 'sqlite:////tmp/missing-panel-test.sqlite', lambda: {})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://panel') as client:
                availability = patch('dashboard.probe_services', new=AsyncMock(return_value={'listo':True,'bcb':True,'bancos':[]}))
                availability.start()
                self.addCleanup(availability.stop)
                response = await client.get('/panel')
                self.assertEqual(response.status_code, 200)
                self.assertIn('Conversión interbancaria', response.text)
                self.assertEqual((await client.get('/panel/assets/app.js')).status_code, 200)
                self.assertEqual((await client.post('/api/panel/ejecutar', headers={'origin': 'http://otro'})).status_code, 403)
                self.assertEqual((await client.post('/api/panel/ejecutar')).status_code, 202)
                await asyncio.sleep(0)
                self.assertEqual((await client.post('/api/panel/ejecutar')).status_code, 409)
                event.set()
                await asyncio.sleep(0)
                self.assertEqual(len(calls), 1)
        asyncio.run(run())

    def test_start_rejects_missing_banks_without_running_conversion(self):
        async def run():
            app = FastAPI()
            execute = AsyncMock()
            install_dashboard(app, execute, lambda: 'http://bcb/rate', lambda: '', lambda: {1:'http://bank'})
            availability = {'listo':False,'bcb':True,'bancos':[{'banco_id':1,'disponible':False}]}
            with patch('dashboard.probe_services', new=AsyncMock(return_value=availability)):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://panel') as client:
                    response = await client.post('/api/panel/ejecutar')
                    self.assertEqual(response.status_code, 503)
                    self.assertIn('APIs bancarias no disponibles: 1', response.json()['detail'])
            execute.assert_not_called()
        asyncio.run(run())

    def test_interval_validation_and_proxy(self):
        async def run():
            app = FastAPI()
            install_dashboard(app, lambda: None, lambda: 'http://bcb/api/bcb/tipo-cambio', lambda: '', lambda: {})
            client_class = httpx.AsyncClient
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(200, json={'intervalo_actual_segundos': 1})
            async with client_class(transport=httpx.ASGITransport(app=app), base_url='http://panel') as client:
                with patch('dashboard.httpx.AsyncClient', side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw)):
                    self.assertEqual((await client.put('/api/panel/intervalo', json={'segundos': 0})).status_code, 422)
                    self.assertEqual((await client.put('/api/panel/intervalo', json={'segundos': 1})).status_code, 200)
            self.assertEqual(calls[0].url.path, '/api/bcb/configurar-intervalo')
            self.assertEqual(calls[0].url.params['segundos'], '1')
        asyncio.run(run())

    def test_verification_reads_the_bank_and_detects_mismatch(self):
        async def run(directory):
            root = Path(directory)
            store = SQLiteStore('sqlite:///' + str(root / 'bank.sqlite'))
            store.upsert_account(encrypted())
            request = ConfirmationRequest(**confirmation(amount='859.2586'))
            store.confirm(request)
            journal_url = 'sqlite:///' + str(root / 'asfi.sqlite')
            journal = Journal(journal_url)
            record = dict(banco_id=3,cuenta_id='1',saldo_usd='123.4567',saldo_bs='859.2586',tipo_cambio='6.9600',
                          codigo_verificacion='1234ABCD',timestamp=request.converted_at.isoformat())
            rows = journal.prepare([record]); rows[0]['estado'] = 'CONFIRMADA'; journal.finish(rows); journal.close()
            bank = FastAPI(); bank.include_router(create_bank_router(store, 3))
            panel = FastAPI()
            install_dashboard(panel, lambda: None, lambda: '', lambda: journal_url, lambda: {3: 'http://bank/api/banco'})
            client_class = httpx.AsyncClient
            async with client_class(transport=httpx.ASGITransport(app=panel), base_url='http://panel') as client:
                with patch('dashboard.httpx.AsyncClient', side_effect=lambda **kw: client_class(transport=httpx.ASGITransport(app=bank), **kw)):
                    response = await client.get('/api/panel/verificar?banco=3&cuenta=1')
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertTrue(response.json()['coincide'], response.text)
                    store._connection.execute("UPDATE cuentas SET saldo_bs='1.0000' WHERE nro='1'")
                    store._connection.commit()
                    response = await client.get('/api/panel/verificar?banco=3&cuenta=1')
                    self.assertFalse(response.json()['coincide'])
            store._connection.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(run(directory))
