"""Pruebas unitarias e integradas para la Tarea 2:
BDs NoSQL (MongoDB & Redis) y APIs Bancos 8 al 14.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pymongo
import redis
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "asfi-service"))
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from crypto.ciphers import ECCCipher
from crypto.key_manager import CipherFactory, BANK_CONFIG
from common.bank_router import BANK_METADATA
from common.mongo_store import MongoStore
from common.redis_store import RedisStore

NOSQL_BANK_CONFIGS = {
    8: {"name": "Banco Prodem S.A.", "db": "bank_prodem", "algorithm": "Blowfish", "port": 8108},
    9: {"name": "Banco Solidario S.A.", "db": "bank_solidario", "algorithm": "Twofish", "port": 8109},
    10: {"name": "Banco Fortaleza S.A.", "db": "bank_fortaleza", "algorithm": "AES", "port": 8110},
    11: {"name": "Banco FIE S.A.", "db": "bank_fie", "algorithm": "RSA", "port": 8111},
    12: {"name": "Banco PYME de la Comunidad S.A.", "db": "bank_pyme", "algorithm": "ElGamal", "port": 8112},
    13: {"name": "Banco de Desarrollo Productivo S.A.M.", "db": "bank_bdp", "algorithm": "ECC", "port": 8113},
    14: {"name": "Banco de la Nación Argentina", "db": "bank_argentina", "algorithm": "ChaCha20", "port": 8114},
}


class TestCryptoAlgorithms(unittest.TestCase):
    """Verifica que cada uno de los 7 algoritmos cifre y descifre sin mezclarse."""

    def test_all_seven_algorithms(self):
        for bank_id, info in NOSQL_BANK_CONFIGS.items():
            cipher, key = CipherFactory.get_cipher_for_bank(bank_id)
            plain_balance = "12500.7500"

            # Claves asimétricas o simétricas
            enc_key = key.public_key() if isinstance(cipher, ECCCipher) else key
            encrypted = cipher.encrypt(plain_balance, enc_key)

            self.assertIsInstance(encrypted, str)
            self.assertNotEqual(encrypted, plain_balance)

            decrypted = cipher.decrypt(encrypted, key)
            self.assertEqual(
                decrypted,
                plain_balance,
                f"Fallo en descifrado para Banco {bank_id} ({info['name']} - {info['algorithm']})",
            )
            # Verificar nombre del algoritmo
            self.assertEqual(BANK_CONFIG[bank_id]["type"], info["algorithm"])


class TestNoSQLDatabasesIsolation(unittest.TestCase):
    """Verifica la persistencia, índices y aislamiento lógico en MongoDB y Redis."""

    @classmethod
    def setUpClass(cls):
        cls.mongo_client = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        cls.redis_client = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

    @classmethod
    def tearDownClass(cls):
        cls.mongo_client.close()
        cls.redis_client.close()

    def test_mongo_databases_exist_and_isolated(self):
        for bank_id, info in NOSQL_BANK_CONFIGS.items():
            db = self.mongo_client[info["db"]]
            count = db.cuentas.count_documents({})
            self.assertGreater(count, 0, f"La base {info['db']} del Banco {bank_id} debe tener cuentas")

            # Verificar que TODAS las cuentas en esta base pertenezcan exclusivamente a este banco
            foreign_accounts = db.cuentas.count_documents({"id_banco": {"$ne": bank_id}})
            self.assertEqual(
                foreign_accounts,
                0,
                f"La base {info['db']} contiene cuentas de otro banco (violación de aislamiento)",
            )

    def test_mongo_indexes_created(self):
        for bank_id, info in NOSQL_BANK_CONFIGS.items():
            db = self.mongo_client[info["db"]]
            indexes = [idx["name"] for idx in db.cuentas.list_indexes()]
            self.assertIn("nro_1", indexes, f"Falta índice nro_1 en {info['db']}")
            self.assertIn("id_banco_1", indexes, f"Falta índice id_banco_1 en {info['db']}")
            self.assertIn("codigo_verificacion_1", indexes, f"Falta índice codigo_verificacion_1 en {info['db']}")

    def test_redis_namespaces_isolated(self):
        for bank_id in NOSQL_BANK_CONFIGS:
            keys = list(self.redis_client.scan_iter(match=f"bank:{bank_id}:cuenta:*"))
            self.assertGreater(len(keys), 0, f"Namespace bank:{bank_id} en Redis debe tener cuentas")


class TestBankRestAPIs(unittest.TestCase):
    """Prueba exhaustiva de las APIs REST para cada uno de los Bancos 8 al 14."""

    @classmethod
    def setUpClass(cls):
        cls.mongo_client = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
        cls.redis_client = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

    @classmethod
    def tearDownClass(cls):
        cls.mongo_client.close()
        cls.redis_client.close()

    def setUp(self):
        # Asegurar estado limpio antes de cada prueba unitaria
        for bank_id, info in NOSQL_BANK_CONFIGS.items():
            db = self.mongo_client[info["db"]]
            db.cuentas.update_many(
                {},
                {"$set": {"estado": "PENDIENTE", "codigo_verificacion": None, "saldo_bs": None}},
            )
            for k in self.redis_client.scan_iter(match=f"bank:{bank_id}:cuenta:*"):
                self.redis_client.hset(k, mapping={"estado": "PENDIENTE", "codigo_verificacion": "", "saldo_bs": ""})
            for k in self.redis_client.scan_iter(match=f"bank:{bank_id}:tx:*"):
                self.redis_client.delete(k)

    def _create_client_for_bank(self, bank_id: int) -> TestClient:
        info = NOSQL_BANK_CONFIGS[bank_id]
        storage = "redis" if bank_id == 10 else "mongo"
        db_url = (
            f"redis://127.0.0.1:6379/0#bank{bank_id}"
            if storage == "redis"
            else f"mongodb://127.0.0.1:27017/{info['db']}"
        )
        from bank_template.main import create_app

        bank_app = create_app(bank_id=bank_id, storage=storage, database_url=db_url)
        return TestClient(bank_app)


    def test_health_and_info_endpoints(self):
        for bank_id in range(8, 15):
            client = self._create_client_for_bank(bank_id)
            resp = client.get("/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["bank_id"], bank_id)
            self.assertGreater(data["total_cuentas"], 0)

            resp_info = client.get("/api/banco/info")
            self.assertEqual(resp_info.status_code, 200)
            info_data = resp_info.json()
            self.assertEqual(info_data["banco_id"], bank_id)
            self.assertEqual(info_data["algoritmo"], NOSQL_BANK_CONFIGS[bank_id]["algorithm"])

    def test_get_cuentas_and_pagination(self):
        for bank_id in range(8, 15):
            client = self._create_client_for_bank(bank_id)

            # 1. Ruta directa: GET /cuentas
            resp = client.get("/cuentas")
            self.assertEqual(resp.status_code, 200, f"Error en GET /cuentas Banco {bank_id}")
            data = resp.json()
            self.assertEqual(data["banco_id"], bank_id)
            self.assertIsInstance(data["cuentas"], list)
            self.assertGreater(len(data["cuentas"]), 0)

            # Verificar campos mínimos requeridos por la práctica
            first_account = data["cuentas"][0]
            self.assertIn("Nro", first_account)
            self.assertIn("CuentaId", first_account)
            self.assertIn("Saldo", first_account)
            self.assertIn("SaldoUSD", first_account)
            self.assertIn("IdBanco", first_account)
            self.assertIn("BancoId", first_account)
            self.assertEqual(first_account["IdBanco"], bank_id)

            # 2. Ruta compatible ASFI: GET /api/banco/cuentas/cifradas
            resp_asfi = client.get("/api/banco/cuentas/cifradas?offset=0&limit=100")
            self.assertEqual(resp_asfi.status_code, 200)
            data_asfi = resp_asfi.json()
            self.assertEqual(len(data_asfi["cuentas"]), len(data["cuentas"]))

            # 3. Ruta REST: GET /api/bancos/{bank_id}/cuentas
            resp_rest = client.get(f"/api/bancos/{bank_id}/cuentas")
            self.assertEqual(resp_rest.status_code, 200)

            # 4. Paginación: offset y limit
            resp_paged = client.get("/cuentas?offset=0&limit=2")
            self.assertEqual(resp_paged.status_code, 200)
            self.assertLessEqual(len(resp_paged.json()["cuentas"]), 2)

    def test_get_single_account(self):
        for bank_id in range(8, 15):
            client = self._create_client_for_bank(bank_id)
            accounts = client.get("/cuentas").json()["cuentas"]
            target_ref = accounts[0]["Nro"]

            # Consulta por ID existente
            resp = client.get(f"/api/banco/cuentas/{target_ref}")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["cuenta"]["Nro"], target_ref)

            # Consulta por ID inexistente
            resp_404 = client.get("/api/banco/cuentas/CUENTA_INEXISTENTE_9999")
            self.assertEqual(resp_404.status_code, 404)

    def test_post_confirmar_validations_and_lifecycle(self):
        """Prueba exhaustiva de POST /confirmar: formato hex 8 dígitos, actualización, anti-replay e idempotencia."""
        for bank_id in range(8, 15):
            client = self._create_client_for_bank(bank_id)
            accounts = client.get("/cuentas").json()["cuentas"]
            self.assertGreater(len(accounts), 1, f"Banco {bank_id} debe tener al menos 2 cuentas")

            account_to_confirm = accounts[-1]["Nro"]  # Tomar la última cuenta
            valid_code = f"A{bank_id:02d}F0001"[-8:].upper()  # Exactamente 8 caracteres hex

            # A. Validación de formato de código hexadecimal de 8 caracteres
            # 1. Menos de 8 caracteres
            resp_short = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": "ABC12",
                    "saldo_bs": "5000.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_short.status_code, 422, "Debe rechazar códigos de menos de 8 caracteres")

            # 2. Más de 8 caracteres
            resp_long = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": "ABC123456789",
                    "saldo_bs": "5000.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_long.status_code, 422, "Debe rechazar códigos de más de 8 caracteres")

            # 3. Caracteres no hexadecimales (ej. letras G-Z)
            resp_nonhex = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": "ZZZZZZZZ",
                    "saldo_bs": "5000.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_nonhex.status_code, 422, "Debe rechazar caracteres no hexadecimales")

            # B. Cuenta inexistente (404)
            resp_not_found = client.post(
                "/confirmar",
                json={
                    "account_ref": "NO_EXISTE_99999",
                    "verification_code": "DEADBEEF",
                    "saldo_bs": "5000.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_not_found.status_code, 404, "Debe retornar 404 para cuenta inexistente")

            # C. Confirmación exitosa con código válido de 8 caracteres
            resp_ok = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": valid_code,
                    "saldo_bs": "8700.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_ok.status_code, 200, f"Error en confirmación de Banco {bank_id}: {resp_ok.text}")
            conf_data = resp_ok.json()
            self.assertEqual(conf_data["status"], "CONFIRMADA")
            self.assertEqual(conf_data["verification_code"], valid_code)

            # D. Verificar persistencia: el estado ahora es CONFIRMADA
            acc_check = client.get(f"/api/banco/cuentas/{account_to_confirm}").json()["cuenta"]
            self.assertEqual(acc_check["Estado"], "CONFIRMADA")
            self.assertEqual(acc_check["CodigoVerificacion"], valid_code)
            self.assertEqual(acc_check["SaldoBs"], "8700.0000")

            # E. Idempotencia: reenvío del MISMO código debe responder 200 OK
            resp_retry = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": valid_code,
                    "saldo_bs": "8700.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(resp_retry.status_code, 200, "Reintento con el mismo código debe ser idempotente (200)")

            # F. Anti-Replay: intento de reutilización o sobreescritura con CÓDIGO DISTINTO debe ser rechazado (409)
            resp_tamper = client.post(
                "/confirmar",
                json={
                    "account_ref": account_to_confirm,
                    "verification_code": "FFFF0000",  # Código diferente
                    "saldo_bs": "9999.0000",
                    "exchange_rate": "6.9600",
                },
            )
            self.assertEqual(
                resp_tamper.status_code,
                409,
                f"Debe rechazar con 409 Conflict si la transacción ya fue confirmada con otro código",
            )

    def test_asfi_end_to_end_flow_banks_8_to_14(self):
        """Simula el flujo completo de barrido de ASFI sobre los Bancos 8 al 14."""
        import secrets

        # Limpiar estado en Mongo y Redis para esta prueba
        for bank_id in range(8, 15):
            info = NOSQL_BANK_CONFIGS[bank_id]
            self.mongo_client[info["db"]].cuentas.update_many(
                {},
                {"$set": {"estado": "PENDIENTE", "codigo_verificacion": None, "saldo_bs": None}},
            )
            for k in self.redis_client.scan_iter(match=f"bank:{bank_id}:cuenta:*"):
                self.redis_client.hset(k, mapping={"estado": "PENDIENTE", "codigo_verificacion": "", "saldo_bs": ""})
            for k in self.redis_client.scan_iter(match=f"bank:{bank_id}:tx:*"):
                self.redis_client.delete(k)

        tasa_bcb = Decimal("6.9600")
        total_procesadas = 0
        total_confirmadas = 0

        for bank_id in range(8, 15):
            client = self._create_client_for_bank(bank_id)
            resp = client.get("/api/banco/cuentas/cifradas?limit=100")
            self.assertEqual(resp.status_code, 200)
            accounts = resp.json().get("cuentas", [])
            self.assertGreater(len(accounts), 0)

            cipher, key = CipherFactory.get_cipher_for_bank(bank_id)
            if hasattr(key, "public_key") and cipher.__class__.__name__ == "ECCCipher":
                key = key

            for acc in accounts:
                saldo_cifrado = acc["Saldo"]
                saldo_usd = Decimal(str(cipher.decrypt(saldo_cifrado, key)).strip().replace(" ", ""))
                saldo_bs = (saldo_usd * tasa_bcb).quantize(Decimal("0.0001"))
                hex_code = secrets.token_hex(4).upper()

                conf_resp = client.post(
                    "/api/banco/cuentas/confirmar",
                    json={
                        "account_ref": str(acc["Nro"]),
                        "verification_code": hex_code,
                        "saldo_bs": format(saldo_bs, "f"),
                        "exchange_rate": format(tasa_bcb, "f"),
                        "converted_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                self.assertEqual(conf_resp.status_code, 200)
                conf_data = conf_resp.json()
                self.assertEqual(conf_data["status"], "CONFIRMADA")
                total_procesadas += 1
                total_confirmadas += 1

        self.assertEqual(total_procesadas, 35, "Deben haberse procesado 35 cuentas en los 7 bancos NoSQL")
        self.assertEqual(total_confirmadas, 35, "Todas las 35 cuentas deben quedar CONFIRMADAS con 0 errores")


if __name__ == "__main__":
    unittest.main()

