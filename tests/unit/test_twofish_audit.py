import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_pipeline import asfi
from crypto.ciphers import TwofishCipher
from Crypto.Cipher import AES
from crypto.twofish_backend import Twofish

class TwofishTests(unittest.TestCase):
    def test_known_vectors(self):
        # Vectores Twofish de clave y bloque cero, 128 y 256 bits.
        for size,expected in [(16,'9F589F5CF6122C32B6BFEC2F2AE8C35A'),(32,'57FF739D4DC92C1BD7FC01700CC8216F')]:
            cipher=Twofish(bytes(size))
            self.assertEqual(cipher.encrypt(bytes(16)).hex().upper(),expected)
            self.assertEqual(cipher.decrypt(bytes.fromhex(expected)),bytes(16))

    def test_version_authentication_and_legacy(self):
        c=TwofishCipher();plain='José Muñoz — 123.4567'
        encoded=c.encrypt(plain)
        self.assertTrue(encoded.startswith('TF1:'))
        self.assertEqual(c.decrypt(encoded),plain)
        self.assertNotEqual(c.encrypt(plain),encoded)
        with self.assertRaises(ValueError):c.decrypt(encoded,'wrong')
        raw=bytearray(base64.b64decode(encoded[4:]));raw[17]^=1
        with self.assertRaises(ValueError):c.decrypt('TF1:'+base64.b64encode(raw).decode())
        legacy=AES.new(c._prepare_key(None)[:16],AES.MODE_CTR,nonce=b'TwofishN').encrypt(plain.encode())
        self.assertEqual(c.decrypt(base64.b64encode(legacy).decode()),plain)
        for text in ['', 'X'*16, 'Ñ'*100]:self.assertEqual(c.decrypt(c.encrypt(text)),text)

class AuditTests(unittest.TestCase):
    def test_run_metadata_and_failure(self):
        async def run(path):
            async def fake(*args):
                await asyncio.to_thread(asfi.append_audit,[dict(banco_id=1,cuenta_id='7',estado='ERROR',detail='Saldo inválido',datos={'secret':'hidden'})])
                return {'status':'PARCIAL','errores':1}
            with patch.object(asfi,'AUDIT_FILE',path),patch.object(asfi,'_execute_conversion',fake):
                first=await asfi.execute_conversion()
                second=await asfi.execute_conversion()
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertNotEqual(first['barrido_id'],second['barrido_id'])
            for row in rows:
                self.assertIn('audit_timestamp',row);self.assertIn('barrido_id',row)
                self.assertNotIn('datos',row)
            self.assertEqual({r['barrido_id'] for r in rows[:3]},{first['barrido_id']})
            self.assertEqual(rows[0]['evento'],'INICIO_BARRIDO')
            self.assertEqual(rows[2]['evento'],'FIN_BARRIDO')
            async def fail(*args):raise ValueError('fallo controlado')
            with patch.object(asfi,'AUDIT_FILE',path),patch.object(asfi,'_execute_conversion',fail):
                with self.assertRaises(ValueError):await asfi.execute_conversion()
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])['evento'],'FALLO_BARRIDO')
            self.assertIsNone(asfi.AUDIT_RUN.get())
        with tempfile.TemporaryDirectory() as d:asyncio.run(run(Path(d)/'audit.jsonl'))
