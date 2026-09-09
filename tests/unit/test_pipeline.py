import asyncio
import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'banks-services'),str(ROOT/'asfi-service')]
from scripts.seeder import load_rows,seed,COLUMNS
from scripts.load_common import load
from common.sqlite_store import SQLiteStore
from common.bank_router import ConfirmationRequest,create_bank_router
from crypto.key_manager import CipherFactory
from crypto.ciphers import ECCCipher
from shared.money import parse_money,convert_money
from journal import Journal
from fastapi import FastAPI
import httpx
spec=importlib.util.spec_from_file_location('asfi_main_test',ROOT/'asfi-service/main.py')
asfi=importlib.util.module_from_spec(spec);spec.loader.exec_module(asfi)


def plain(n=1,bank=3,balance='123.4567'):
    return dict(zip(COLUMNS,[str(n),'123','José','Muñoz',f'ABC{n}',str(bank),balance]))


def encrypted(n=1,bank=3):
    c,k=CipherFactory.get_cipher_for_bank(bank)
    row=plain(n,bank)
    for f in ('Identificacion','Nombres','Apellidos','NroCuenta','Saldo'):
        row[f]=c.encrypt(row[f],k.public_key() if isinstance(c,ECCCipher) else k)
    return row


def confirmation(n=1,code='1234ABCD',amount='859.2586'):
    return dict(account_ref=str(n),verification_code=code,saldo_bs=amount,exchange_rate='6.9600',converted_at=datetime.now(timezone.utc).isoformat())


class PipelineTests(unittest.TestCase):
    def test_money(self):
        for bad in ('NaN','Infinity','1e9999','1e-999','1.23456','1.2.3','1.000,25','100000000000000'):
            with self.subTest(bad=bad),self.assertRaises(ValueError): parse_money(bad)
        self.assertEqual(str(parse_money('1,234.5678')),'1234.5678')
        self.assertEqual(str(convert_money('10.0000','6.9600')),'69.6000')

    def test_unicode_roundtrip_all_banks(self):
        for bank in range(1,15):
            c,k=CipherFactory.get_cipher_for_bank(bank)
            key=k.public_key() if isinstance(c,ECCCipher) else k
            for text in ('José Muñoz','Jj 324443.5414','ÁÉÍÓÚ ñ 😀'):
                with self.subTest(bank=bank,text=text):
                    self.assertEqual(c.decrypt(c.encrypt(text,key),k),text)

    def test_bad_csv_continues_and_canonical_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'data.csv'
            file.write_text(','.join(COLUMNS)+'\n1,123,A,B,C,1,2,extra\n2,123,A,B,C,1,NaN\n"oops\n3,123,José,Muñoz,C,3,12\n003,123,A,B,C,3,12\n4,123,A,B,C,3,20\n',encoding='utf-8')
            result=load_rows(file)
            self.assertEqual(result.total_read,6)
            self.assertEqual(len(result.rejected_rows),4)
            self.assertEqual([r['Nro'] for r in result.valid_rows],['3','4'])

    def test_seed_load_batch_and_retry(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'source.csv'
            with source.open('w') as file:
                writer=csv.DictWriter(file,fieldnames=COLUMNS);writer.writeheader();writer.writerows(plain(n) for n in range(1,1101))
            metrics=seed(source,d/'seed',workers=1,batch_size=17)
            self.assertEqual(metrics['cifradas'],1100)
            store=SQLiteStore('sqlite:///'+str(d/'bank.sqlite'))
            result=load(d/'seed/bank_03.jsonl',store,batch_size=200,expected_bank=3)
            self.assertEqual(result['cargadas'],1100)
            r=ConfirmationRequest(**confirmation())
            store.confirm(r)
            load(d/'seed/bank_03.jsonl',store,batch_size=200)
            self.assertEqual(store.confirm(r)['status'],'CONFIRMADA')
            with self.assertRaises(ValueError):store.confirm(ConfirmationRequest(**confirmation(code='ABCD1234')))
            with self.assertRaises(ValueError):store.confirm(ConfirmationRequest(**confirmation(amount='1.0000')))
            self.assertEqual(store._connection.execute('SELECT count(*) FROM cuentas').fetchone()[0],1100)
            store._connection.close()

    def test_batch_http_partial_validation(self):
        async def run(d):
            store=SQLiteStore('sqlite:///'+str(Path(d)/'bank.sqlite'))
            store.upsert_accounts_batch([encrypted(1),encrypted(2)])
            app=FastAPI();app.include_router(create_bank_router(store,3))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post('/api/banco/cuentas/confirmar',json=[confirmation(1),confirmation(2,code='invalid'),confirmation(99)])
                self.assertEqual(response.status_code,200)
                results=response.json()['resultados']
                self.assertEqual(sum(r['status']=='CONFIRMADA' for r in results),1)
                self.assertEqual(sum(r['status']=='ERROR' for r in results),2)
            store._connection.close()
        with tempfile.TemporaryDirectory() as d:asyncio.run(run(d))

    def test_asfi_resume_and_variable_rate(self):
        async def run(d):
            d=Path(d);store=SQLiteStore('sqlite:///'+str(d/'bank.sqlite'))
            store.upsert_accounts_batch([encrypted(1),encrypted(2)])
            app=FastAPI();app.include_router(create_bank_router(store,3))
            rates=[]
            @app.get('/bcb')
            def bcb():
                rate='6.9600' if not rates else '7.0000'
                rates.append(rate)
                return dict(tipo_cambio=rate,timestamp=datetime.now(timezone.utc).isoformat(),intervalo_actual_segundos=180)
            with patch.dict(os.environ,{'ACTIVE_BANK_IDS':'3','BANK_URL_3':'http://test/api/banco','ASFI_BATCH_SIZE':'1','ASFI_CRYPTO_WORKERS':'0'}),patch.object(asfi,'BCB_URL','http://test/bcb'),patch.object(asfi,'DATABASE_URL','sqlite:///'+str(d/'asfi.sqlite')),patch.object(asfi,'AUDIT_FILE',d/'audit.jsonl'):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    result=await asfi.execute_conversion(client)
                    self.assertEqual(result['confirmadas'],2,result)
                    self.assertEqual(result['errores'],0,result)
                    journal=Journal(asfi.DATABASE_URL)
                    saved=[json.loads(r[0]) for r in journal.db.execute('SELECT payload FROM asfi_cuentas ORDER BY cuenta_id')]
                    self.assertEqual([r['tipo_cambio'] for r in saved],['6.9600','7.0000'])
                    # Mismos datos descifrados, distinta huella del cifrado anterior.
                    for record in saved:
                        record['origen_hash']='cifrado-anterior'
                    journal.finish(saved)
                    # Simular caída después de confirmar al banco pero antes de guardar el recibo.
                    journal.db.execute("UPDATE asfi_cuentas SET estado='PENDIENTE' WHERE cuenta_id='1'");journal.db.commit();journal.close()
                    again=await asfi.execute_conversion(client)
                    self.assertEqual(again['confirmadas'],1,again)
                    self.assertEqual(again['ya_confirmadas'],1,again)
                    self.assertEqual(again['errores'],0,again)
                    journal=Journal(asfi.DATABASE_URL)
                    stale=list(journal.lookup(3,['1','2']).values())
                    for record in stale:record['origen_hash']='otra-representacion'
                    journal.finish(stale);journal.close()
                    fresh=await asfi.execute_conversion(client,new_round=True)
                    self.assertEqual(fresh['confirmadas'],2,fresh)
                    self.assertEqual(fresh['errores'],0,fresh)
                    journal=Journal(asfi.DATABASE_URL)
                    current=journal.lookup(3,['1','2'])
                    self.assertEqual(current['1']['tipo_cambio'],'7.0000')
                    self.assertNotEqual(current['1']['codigo_verificacion'],saved[0]['codigo_verificacion'])
                    self.assertEqual(journal.db.execute('SELECT count(*) FROM asfi_historial').fetchone()[0],2)
                    for ref,record in current.items():
                        bank=store.get_account(ref)
                        self.assertEqual(bank['codigo_verificacion'],record['codigo_verificacion'])
                        self.assertEqual(parse_money(bank['saldo_bs']),parse_money(record['saldo_bs']))
                    journal.close()
                    # Un saldo realmente distinto debe seguir siendo rechazado.
                    cipher,key=CipherFactory.get_cipher_for_bank(3)
                    altered={'Saldo':cipher.encrypt('999.0000',key)}
                    store._connection.execute('UPDATE cuentas SET saldo=? WHERE nro=?',(altered['Saldo'],'1'))
                    store._connection.commit()
                    rejected=await asfi.execute_conversion(client,new_round=True)
                    self.assertEqual(rejected['errores'],1,rejected)
                    self.assertEqual(rejected['confirmadas'],1,rejected)
                    self.assertEqual(store.get_account('1')['codigo_verificacion'],current['1']['codigo_verificacion'])

            store._connection.close()
        with tempfile.TemporaryDirectory() as d:asyncio.run(run(d))


class FailureIsolationTests(unittest.TestCase):
    def test_database_bad_row_does_not_discard_good_rows(self):
        import sqlite3
        class Store:
            def __init__(self):self.saved=[]
            def upsert_accounts_batch(self,rows):
                if any(r['Nro']=='2' for r in rows):raise sqlite3.DataError('injected bad row')
                self.saved.extend(rows)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bank_03.jsonl'
            path.write_text('\n'.join(json.dumps(encrypted(i)) for i in range(1,4)))
            store=Store();result=load(path,store)
            self.assertEqual(result['cargadas'],2)
            self.assertEqual(result['rechazadas'],1)

    def test_rejected_rate_does_not_confirm(self):
        async def run():
            for rate in ('NaN','-1','100','0'):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=dict(tipo_cambio=rate,timestamp=datetime.now(timezone.utc).isoformat(),intervalo_actual_segundos=180)))) as client:
                    with self.assertRaises(ValueError):await asfi.get_exchange_rate(client)
        asyncio.run(run())

    def test_corrupted_cipher_isolated_in_batch(self):
        records=[encrypted(1,4),encrypted(2,4),encrypted(3,4)]
        records[1]['Saldo']='\ue001'.join(['\ue000','','1','A'])
        output=asfi.decrypt_batch(4,records)
        self.assertEqual(sum(r.get('estado')=='ERROR' for r in output),1)
        self.assertEqual(len(output),3)

    def test_retries_use_identical_confirmation(self):
        async def run():
            calls=[]
            def handler(request):
                calls.append(request.content)
                return httpx.Response(503 if len(calls)<3 else 200,json={})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await asfi.request_retry(client,'POST','http://test/confirm',json=[confirmation()])
            self.assertEqual(len(calls),3)
            self.assertEqual(len(set(calls)),1)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
