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

    def upsert_account(self, record: dict[str, Any]) -> None:
        query = """
        MERGE (cliente:Cliente {identificacion: $identificacion})
        SET cliente.nombres = $nombres, cliente.apellidos = $apellidos
        MERGE (cuenta:Cuenta {nro: $nro})
        SET cuenta.identificacion = $identificacion,
            cuenta.nombres = $nombres, cuenta.apellidos = $apellidos,
            cuenta.nro_cuenta = $nro_cuenta, cuenta.id_banco = $id_banco,
            cuenta.saldo = $saldo
        MERGE (cliente)-[:TIENE_CUENTA]->(cuenta)
        """
        with self._driver.session() as session:
            session.run(
                query,
                nro=str(record["Nro"]),
                identificacion=record["Identificacion"],
                nombres=record["Nombres"],
                apellidos=record["Apellidos"],
                nro_cuenta=record["NroCuenta"],
                id_banco=int(record["IdBanco"]),
                saldo=record["Saldo"],
            ).consume()

    def close(self) -> None:
        self._driver.close()
