import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_pipeline import encrypted, confirmation
from common.sqlite_store import SQLiteStore
from common.bank_router import ConfirmationRequest


class LegacySchemaTests(unittest.TestCase):
    def test_migration_keeps_confirmation_and_accepts_new_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite'
            original = encrypted(1)
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE cuentas (nro TEXT PRIMARY KEY, identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,apellidos TEXT NOT NULL,nro_cuenta TEXT NOT NULL,id_banco INTEGER NOT NULL,
                    saldo TEXT NOT NULL,saldo_bs TEXT,codigo_verificacion TEXT,tipo_cambio TEXT,convertido_at TEXT)''')
                db.execute('INSERT INTO cuentas VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (original['Nro'],original['Identificacion'],original['Nombres'],original['Apellidos'],
                            original['NroCuenta'],3,original['Saldo'],'859.2586','1234ABCD','6.9600','2026-09-09T00:00:00+00:00'))
            store = SQLiteStore('sqlite:///' + str(path))
            self.assertEqual(store.encrypted_accounts(0,10)[0]['Saldo'], original['Saldo'])
            self.assertEqual(store.get_account('1')['codigo_verificacion'], '1234ABCD')
            store.upsert_account(encrypted(2))
            self.assertEqual(store.count_accounts(), 2)
            store._connection.close()
            store = SQLiteStore('sqlite:///' + str(path))
            self.assertEqual(store.count_accounts(), 2)
            self.assertEqual(store.confirm(ConfirmationRequest(**confirmation()))['status'], 'CONFIRMADA')
            store._connection.close()
