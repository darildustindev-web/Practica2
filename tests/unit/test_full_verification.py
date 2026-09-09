import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.verificar_consolidacion import verify

class FullVerificationTests(unittest.TestCase):
    def exercise(self, alter=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'asfi.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE asfi_cuentas (banco_id INTEGER,cuenta_id TEXT,saldo_usd TEXT,saldo_bs TEXT,tipo_cambio TEXT,codigo_verificacion TEXT,estado TEXT)')
                for bank in range(1,15):
                    (root/f'bank_{bank:02d}.jsonl').write_text(json.dumps({'Nro':'1'})+'\n')
                    db.execute('INSERT INTO asfi_cuentas VALUES (?,?,?,?,?,?,?)',(bank,'1','100.0000','696.0000','6.9600','1234ABCD','CONFIRMADA'))
            def rows(bank):
                if alter and bank==2:return []
                row=dict(ref='1',saldo_bs='696.0000',tipo_cambio='6.9600',codigo_verificacion='1234ABCD')
                if alter and bank==1:row.update(saldo_bs='1.0000',tipo_cambio='7.0000',codigo_verificacion='FFFFFFFF')
                return [row]
            with patch('scripts.verificar_consolidacion.bank_rows',rows),contextlib.redirect_stdout(io.StringIO()):
                return verify(root,'sqlite:///'+str(path))

    def test_all_match(self):
        result=self.exercise();self.assertTrue(result['coincide']);self.assertEqual(result['total_comparadas'],14)

    def test_detects_discrepancies_and_missing(self):
        result=self.exercise(True);self.assertFalse(result['coincide'])
        errors=result['bancos'][0]['errores']
        self.assertEqual(errors,{'saldo':1,'tasa':1,'codigo':1})
        self.assertEqual(result['bancos'][1]['errores']['faltantes_dataset'],1)
