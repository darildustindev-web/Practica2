"""Pruebas unitarias e integradas para la Tarea 3:
BD Orientada a Grafos Neo4j (Banco BDP - Exclusivo 20 pts).
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "asfi-service"))
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from crypto.ciphers import ECCCipher
from crypto.key_manager import CipherFactory
from common.bank_router import ConfirmationRequest
from common.neo4j_store import Neo4jStore
from bank_template.main import create_app

NEO4J_BOLT_URL = os.getenv("NEO4J_URL", "neo4j://neo4j:bdp_password@127.0.0.1:7687")
SEED_FILE = PROJECT_ROOT / "data" / "seed" / "bank_13.jsonl"


class TestBDPNeo4jGraph(unittest.TestCase):
    """Pruebas del motor de grafos Neo4j para el Banco 13 (BDP)."""

    @classmethod
    def setUpClass(cls):
        cls.store = Neo4jStore(NEO4J_BOLT_URL, auto_constraints=True)
        cls._reload_seed()

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    @classmethod
    def _reload_seed(cls):
        with cls.store._driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
        with SEED_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    cls.store.upsert_account(json.loads(line.strip()))

    def setUp(self):
        with self.store._driver.session() as session:
            session.run("""
            MATCH (cu:Cuenta)
            SET cu.estado = 'PENDIENTE',
                cu.saldoBs = null,
                cu.saldo_bs = null,
                cu.codigoVerificacion = null,
                cu.codigo_verificacion = null,
                cu.fechaConversion = null,
                cu.convertido_at = null,
                cu.tipoCambio = null,
                cu.tipo_cambio = null
            """).consume()

    def test_constraints_and_indexes_exist(self):
        with self.store._driver.session() as session:
            constraints = [c["name"] for c in session.run("SHOW CONSTRAINTS").data()]
            self.assertIn("cliente_id_unique", constraints, "Falta restriccion cliente_id_unique")
            self.assertIn("cuenta_id_unique", constraints, "Falta restriccion cuenta_id_unique")

    def test_graph_model_and_idempotent_seeding(self):
        clients_before = self.store.count_clients()
        accounts_before = self.store.count_accounts()
        rels_before = self.store.count_relationships()

        self.assertEqual(clients_before, 5, "Deben existir 5 nodos (:Cliente)")
        self.assertEqual(accounts_before, 5, "Deben existir 5 nodos (:Cuenta)")
        self.assertEqual(rels_before, 5, "Deben existir 5 relaciones [:TIENE_CUENTA]")

        with SEED_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.store.upsert_account(json.loads(line.strip()))

        clients_after = self.store.count_clients()
        accounts_after = self.store.count_accounts()
        rels_after = self.store.count_relationships()

        self.assertEqual(clients_before, clients_after, "Idempotencia violada: nodos (:Cliente) duplicados")
        self.assertEqual(accounts_before, accounts_after, "Idempotencia violada: nodos (:Cuenta) duplicados")
        self.assertEqual(rels_before, rels_after, "Idempotencia violada: relaciones [:TIENE_CUENTA] duplicadas")

    def test_ecc_encryption_and_decryption(self):
        cipher, key = CipherFactory.get_cipher_for_bank(13)
        self.assertIsInstance(cipher, ECCCipher)

        plain_balance = "18750.5000"
        encrypted = cipher.encrypt(plain_balance, key.public_key())
        self.assertIsInstance(encrypted, str)
        self.assertIn("::", encrypted, "El payload ECC debe contener delimitador ::")

        decrypted = cipher.decrypt(encrypted, key)
        self.assertEqual(decrypted, plain_balance)

        acc = self.store.get_account_by_id("13")
        self.assertIsNotNone(acc)
        self.assertIn("::", acc["saldoUSD"], "El saldoUSD en Neo4j debe estar cifrado con ECC")
        decrypted_db_balance = cipher.decrypt(acc["saldoUSD"], key)
        self.assertEqual(decrypted_db_balance, "8700.0000")

    def test_cypher_queries_a_to_h(self):
        # A. Todos los clientes
        clients = self.store.get_all_clients()
        self.assertEqual(len(clients), 5)
        self.assertIn("clienteId", clients[0])
        self.assertIn("nombres", clients[0])

        # B. Todas las cuentas con paginacion
        accounts_paged = self.store.get_all_accounts(offset=0, limit=2)
        self.assertEqual(len(accounts_paged), 2)
        self.assertIn("cuentaId", accounts_paged[0])
        self.assertEqual(accounts_paged[0]["bancoId"], 13)

        # C. Cuentas de un cliente especifico
        first_client_id = clients[0]["clienteId"]
        client_accounts = self.store.get_accounts_by_client(first_client_id)
        self.assertGreaterEqual(len(client_accounts), 1)

        # D. Buscar cuenta por CuentaId
        acc_13 = self.store.get_account_by_id("13")
        self.assertIsNotNone(acc_13)
        self.assertEqual(acc_13["cuentaId"], "13")
        self.assertEqual(acc_13["bancoId"], 13)

        # Cuenta inexistente
        acc_none = self.store.get_account_by_id("NO_EXISTE_9999")
        self.assertIsNone(acc_none)

        # E. Cliente asociado a una cuenta
        client_of_13 = self.store.get_client_by_account("13")
        self.assertIsNotNone(client_of_13)
        self.assertIn("clienteId", client_of_13)

        # F. Relacion TIENE_CUENTA completa
        graph_edges = self.store.get_graph_clients_and_accounts()
        self.assertEqual(len(graph_edges), 5)
        self.assertEqual(graph_edges[0]["relacion"], "TIENE_CUENTA")

        # G. Cuentas pendientes para conversion
        pending = self.store.get_pending_accounts()
        self.assertEqual(len(pending), 5)

        # H. Actualizacion de cuenta (Confirmacion)
        req = ConfirmationRequest(
            account_ref="13",
            verification_code="A1B2C3D4",
            saldo_bs="60552.0000",
            exchange_rate="6.9600",
            converted_at=datetime.now(timezone.utc),
        )
        conf_res = self.store.confirm(req)
        self.assertEqual(conf_res["status"], "CONFIRMADA")
        self.assertEqual(conf_res["verification_code"], "A1B2C3D4")

        updated_acc = self.store.get_account_by_id("13")
        self.assertEqual(updated_acc["estado"], "CONFIRMADA")
        self.assertEqual(updated_acc["codigoVerificacion"], "A1B2C3D4")
        self.assertEqual(updated_acc["saldoBs"], "60552.0000")

    def test_bdp_rest_api_endpoints_and_validations(self):
        app = create_app(bank_id=13, storage="neo4j", database_url=NEO4J_BOLT_URL)
        client = TestClient(app)

        resp_health = client.get("/health")
        self.assertEqual(resp_health.status_code, 200)
        self.assertEqual(resp_health.json()["storage"], "neo4j")
        self.assertEqual(resp_health.json()["db_health"]["neo4j"], "connected")

        resp_info = client.get("/api/banco/info")
        self.assertEqual(resp_info.status_code, 200)
        self.assertEqual(resp_info.json()["banco_id"], 13)
        self.assertEqual(resp_info.json()["algoritmo"], "ECC")

        resp_cuentas = client.get("/cuentas")
        self.assertEqual(resp_cuentas.status_code, 200)
        cuentas = resp_cuentas.json()["cuentas"]
        self.assertEqual(len(cuentas), 5)
        self.assertEqual(cuentas[0]["IdBanco"], 13)

        resp_asfi = client.get("/api/banco/cuentas/cifradas")
        self.assertEqual(resp_asfi.status_code, 200)
        self.assertEqual(len(resp_asfi.json()["cuentas"]), 5)

        resp_clients = client.get("/clientes")
        self.assertEqual(resp_clients.status_code, 200)
        self.assertEqual(resp_clients.json()["total_clientes"], 5)

        resp_grafo = client.get("/grafo")
        self.assertEqual(resp_grafo.status_code, 200)
        self.assertEqual(resp_grafo.json()["total_relaciones"], 5)

        resp_single = client.get("/cuentas/13")
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["cuenta"]["CuentaId"], "13")

        resp_single_404 = client.get("/cuentas/CUENTA_INEXISTENTE")
        self.assertEqual(resp_single_404.status_code, 404)

        # 1. Menos de 8 caracteres
        r_short = client.post("/confirmar", json={"account_ref": "13", "verification_code": "12345", "saldo_bs": "100.0", "exchange_rate": "6.96"})
        self.assertEqual(r_short.status_code, 422)

        # 2. Mas de 8 caracteres
        r_long = client.post("/confirmar", json={"account_ref": "13", "verification_code": "123456789", "saldo_bs": "100.0", "exchange_rate": "6.96"})
        self.assertEqual(r_long.status_code, 422)

        # 3. Caracteres no hexadecimales
        r_nonhex = client.post("/confirmar", json={"account_ref": "13", "verification_code": "ZZZZZZZZ", "saldo_bs": "100.0", "exchange_rate": "6.96"})
        self.assertEqual(r_nonhex.status_code, 422)

        # 4. Cuenta inexistente (404)
        r_notfound = client.post("/confirmar", json={"account_ref": "CUENTA_FANTASMA", "verification_code": "AABB0011", "saldo_bs": "100.0", "exchange_rate": "6.96"})
        self.assertEqual(r_notfound.status_code, 404)

        # 5. Confirmacion exitosa (200 OK)
        r_ok = client.post("/confirmar", json={"account_ref": "13", "verification_code": "DEADBEEF", "saldo_bs": "60552.0000", "exchange_rate": "6.9600"})
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(r_ok.json()["status"], "CONFIRMADA")

        # 6. Idempotencia (200 OK)
        r_idempotent = client.post("/confirmar", json={"account_ref": "13", "verification_code": "DEADBEEF", "saldo_bs": "60552.0000", "exchange_rate": "6.9600"})
        self.assertEqual(r_idempotent.status_code, 200)

        # 7. Anti-replay (409 Conflict)
        r_tamper = client.post("/confirmar", json={"account_ref": "13", "verification_code": "FFFF0000", "saldo_bs": "99999.0000", "exchange_rate": "6.9600"})
        self.assertEqual(r_tamper.status_code, 409)

    def test_asfi_sweep_end_to_end_on_bdp(self):
        app = create_app(bank_id=13, storage="neo4j", database_url=NEO4J_BOLT_URL)
        client = TestClient(app)

        cipher, key = CipherFactory.get_cipher_for_bank(13)
        tasa_bcb = Decimal("6.9600")

        resp = client.get("/api/banco/cuentas/cifradas")
        self.assertEqual(resp.status_code, 200)
        accounts = resp.json()["cuentas"]
        self.assertEqual(len(accounts), 5)

        confirmadas = 0
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
            self.assertEqual(conf_resp.json()["status"], "CONFIRMADA")
            confirmadas += 1

        self.assertEqual(confirmadas, 5, "Las 5 cuentas de BDP en Neo4j deben quedar CONFIRMADAS")


if __name__ == "__main__":
    unittest.main()
