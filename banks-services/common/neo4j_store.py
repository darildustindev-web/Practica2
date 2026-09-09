"""Adaptador Neo4j para Banco 13: clientes, cuentas y relación TIENE_CUENTA."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from neo4j import GraphDatabase

from common.bank_router import ConfirmationRequest


class Neo4jStore:
    def __init__(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"neo4j", "bolt"} or not parsed.hostname:
            raise ValueError("DATABASE_URL de Neo4j debe usar neo4j:// o bolt://")
        user = parsed.username
        password = parsed.password
        if not user or password is None:
            raise ValueError("DATABASE_URL de Neo4j debe incluir usuario y contraseña")
        self._driver = GraphDatabase.driver(
            f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 7687}",
            auth=(user, password),
        )
        self._create_schema()

    def _create_schema(self) -> None:
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Cuenta) REQUIRE c.nro IS UNIQUE").consume()
            session.run("CREATE INDEX IF NOT EXISTS FOR (c:Cliente) ON (c.identificacion)").consume()

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        query = """
        MATCH (cliente:Cliente)-[:TIENE_CUENTA]->(cuenta:Cuenta)
        RETURN cuenta.nro AS Nro, cuenta.identificacion AS Identificacion,
               cuenta.nombres AS Nombres, cuenta.apellidos AS Apellidos,
               cuenta.nro_cuenta AS NroCuenta, cuenta.id_banco AS IdBanco,
               cuenta.saldo AS Saldo
        ORDER BY cuenta.nro SKIP $offset LIMIT $limit
        """
        with self._driver.session() as session:
            return [record.data() for record in session.run(query, offset=offset, limit=limit)]

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        query = """
        MATCH (cuenta:Cuenta {nro: $nro})
        SET cuenta.saldo_bs = $saldo_bs,
            cuenta.codigo_verificacion = $codigo,
            cuenta.tipo_cambio = $tipo_cambio,
            cuenta.convertido_at = $convertido_at
        RETURN cuenta.nro AS nro
        """
        with self._driver.session() as session:
            result = session.run(
                query,
                nro=request.account_ref,
                saldo_bs=request.saldo_bs,
                codigo=request.verification_code.upper(),
                tipo_cambio=request.exchange_rate,
                convertido_at=request.converted_at.isoformat(),
            ).single()
        if result is None:
            raise KeyError("Cuenta no encontrada")
        return {
            "account_ref": request.account_ref,
            "verification_code": request.verification_code.upper(),
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def confirm_batch(self, requests: list[ConfirmationRequest]) -> list[dict[str, Any]]:
        if not requests:
            return []
        query = """
        UNWIND $batch AS row
        MATCH (cuenta:Cuenta {nro: row.nro})
        SET cuenta.saldo_bs = row.saldo_bs,
            cuenta.codigo_verificacion = row.codigo,
            cuenta.tipo_cambio = row.tipo_cambio,
            cuenta.convertido_at = row.convertido_at
        """
        batch = [
            {
                "nro": r.account_ref,
                "saldo_bs": r.saldo_bs,
                "codigo": r.verification_code.upper(),
                "tipo_cambio": r.exchange_rate,
                "convertido_at": r.converted_at.isoformat(),
            }
            for r in requests
        ]
        with self._driver.session() as session:
            session.run(query, batch=batch).consume()
        return [
            {
                "account_ref": r.account_ref,
                "verification_code": r.verification_code.upper(),
                "status": "CONFIRMADA",
                "converted_at": r.converted_at,
            }
            for r in requests
        ]

    def upsert_account(self, record: dict[str, Any]) -> None:
        self.upsert_accounts_batch([record])

    def upsert_accounts_batch(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        query = """
        UNWIND $batch AS row
        MERGE (cliente:Cliente {identificacion: row.identificacion})
        SET cliente.nombres = row.nombres, cliente.apellidos = row.apellidos
        MERGE (cuenta:Cuenta {nro: row.nro})
        SET cuenta.identificacion = row.identificacion,
            cuenta.nombres = row.nombres, cuenta.apellidos = row.apellidos,
            cuenta.nro_cuenta = row.nro_cuenta, cuenta.id_banco = row.id_banco,
            cuenta.saldo = row.saldo
        MERGE (cliente)-[:TIENE_CUENTA]->(cuenta)
        """
        batch = [
            {
                "nro": str(r["Nro"]),
                "identificacion": r["Identificacion"],
                "nombres": r["Nombres"],
                "apellidos": r["Apellidos"],
                "nro_cuenta": r["NroCuenta"],
                "id_banco": int(r["IdBanco"]),
                "saldo": r["Saldo"],
            }
            for r in records
        ]
        with self._driver.session() as session:
            session.run(query, batch=batch).consume()

    def close(self) -> None:
        self._driver.close()
