"""Adaptador Neo4j para Banco 13 (Banco de Desarrollo Productivo - BDP).
Representa el grafo (:Cliente)-[:TIENE_CUENTA]->(:Cuenta), gestiona restricciones de unicidad,
ejecuta consultas Cypher parametrizadas y procesa confirmaciones de conversión monetaria.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from common.bank_router import ConfirmationRequest

logger = logging.getLogger("bank13-neo4j")

HEX_CODE_REGEX = re.compile(r"^[0-9A-Fa-f]{8}$")


from common.nosql_bulk import NoSQLBulk

class Neo4jStore(NoSQLBulk):
    """Adaptador de base de datos orientada a grafos en Neo4j para el Banco BDP."""

    def __init__(self, url: str | None = None, auto_constraints: bool = True):
        raw_url = url or os.getenv(
            "BANK_13_DATABASE_URL",
            os.getenv("NEO4J_URL", "neo4j://neo4j:bdp_password@127.0.0.1:7687"),
        )
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"neo4j", "bolt"} or not parsed.hostname:
            raise ValueError(f"DATABASE_URL de Neo4j debe usar neo4j:// o bolt:// (recibido: '{raw_url}')")

        user = parsed.username or os.getenv("NEO4J_USER", "neo4j")
        password = parsed.password or os.getenv("NEO4J_PASSWORD", "bdp_password")
        if not user or password is None:
            raise ValueError("DATABASE_URL de Neo4j debe incluir usuario y contraseña")

        bolt_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 7687}"
        self._url = bolt_url
        self._driver = GraphDatabase.driver(bolt_url, auth=(user, password))

        # Verificar conectividad temprana
        try:
            self._driver.verify_connectivity()
        except Exception as error:
            raise ConnectionError(f"No se pudo conectar a Neo4j en {bolt_url}: {error}") from error

        if auto_constraints:
            self.ensure_constraints()

    def ensure_constraints(self) -> None:
        """Crea restricciones de unicidad e índices en Neo4j 5.x de forma idempotente."""
        statements = [
            # Restricción de unicidad para Cliente
            "CREATE CONSTRAINT cliente_id_unique IF NOT EXISTS FOR (c:Cliente) REQUIRE c.clienteId IS UNIQUE",
            # Restricción de unicidad para Cuenta
            "CREATE CONSTRAINT cuenta_id_unique IF NOT EXISTS FOR (cu:Cuenta) REQUIRE cu.cuentaId IS UNIQUE",
            # Índices de búsqueda para acelerar consultas de estado y código
            "CREATE INDEX cuenta_banco_id_idx IF NOT EXISTS FOR (cu:Cuenta) ON (cu.bancoId)",
            "CREATE INDEX cuenta_codigo_verif_idx IF NOT EXISTS FOR (cu:Cuenta) ON (cu.codigoVerificacion)",
        ]
        with self._driver.session() as session:
            for stmt in statements:
                try:
                    session.run(stmt).consume()
                except Exception as ex:
                    logger.warning("Aviso al aplicar restricción Neo4j: %s", ex)

    # =========================================================================
    # Inserción / Actualización Idempotente (Poblamiento)
    # =========================================================================
    def upsert_accounts_batch(self, records):
        rows = [dict(cuenta_id=str(r['Nro']), identificacion=r['Identificacion'], nombres=r['Nombres'],
                     apellidos=r['Apellidos'],nro_cuenta=r['NroCuenta'],id_banco=int(r['IdBanco']),
                     saldo=r['Saldo'],estado='PENDIENTE') for r in records]
        query = """
        UNWIND $rows AS row
        MERGE (cuenta:Cuenta {cuentaId: row.cuenta_id})
        ON CREATE SET
            cuenta.nro = row.cuenta_id,
            cuenta.cuentaId = row.cuenta_id,
            cuenta.bancoId = row.id_banco,
            cuenta.id_banco = row.id_banco,
            cuenta.saldo = row.saldo,
            cuenta.saldoUSD = row.saldo,
            cuenta.saldoBs = null,
            cuenta.saldo_bs = null,
            cuenta.estado = row.estado,
            cuenta.codigoVerificacion = null,
            cuenta.codigo_verificacion = null,
            cuenta.fechaConversion = null,
            cuenta.convertido_at = null,
            cuenta.tipoCambio = null,
            cuenta.tipo_cambio = null,
            cuenta.nroCuenta = row.nro_cuenta,
            cuenta.nro_cuenta = row.nro_cuenta,
            cuenta.identificacion = row.identificacion,
            cuenta.nombres = row.nombres,
            cuenta.apellidos = row.apellidos

        WITH cuenta
        MERGE (cliente:Cliente {clienteId: cuenta.identificacion})
        ON CREATE SET cliente.identificacion=cuenta.identificacion,
                      cliente.nombres=cuenta.nombres, cliente.apellidos=cuenta.apellidos
        MERGE (cliente)-[:TIENE_CUENTA]->(cuenta)
        """
        with self._driver.session() as session:
            session.execute_write(lambda tx: tx.run(query, rows=rows).consume())

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])


    def get_all_clients(self) -> list[dict[str, Any]]:
        query = """
        MATCH (c:Cliente)
        RETURN c
        ORDER BY c.clienteId
        """
        with self._driver.session() as session:
            return [dict(record["c"]) for record in session.run(query)]

    # Consulta B: Obtener todas las cuentas (con paginación)
    def get_all_accounts(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        query = """
        MATCH (cu:Cuenta)
        RETURN cu
        ORDER BY cu.cuentaId SKIP $offset LIMIT $limit
        """
        with self._driver.session() as session:
            return [dict(record["cu"]) for record in session.run(query, offset=offset, limit=limit)]

    # Consulta C: Obtener las cuentas de un cliente
    def get_accounts_by_client(self, client_id: str) -> list[dict[str, Any]]:
        query = """
        MATCH (c:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta)
        WHERE c.clienteId = $client_id OR c.identificacion = $client_id
        RETURN cu
        ORDER BY cu.cuentaId
        """
        with self._driver.session() as session:
            return [dict(record["cu"]) for record in session.run(query, client_id=str(client_id))]

    # Consulta D: Buscar una cuenta por CuentaId
    def get_account_by_id(self, account_ref: str) -> dict[str, Any] | None:
        query = """
        MATCH (cu:Cuenta)
        WHERE cu.cuentaId = $account_ref OR cu.nro = $account_ref
        RETURN cu
        """
        with self._driver.session() as session:
            res = session.run(query, account_ref=str(account_ref)).single()
            return dict(res["cu"]) if res else None

    # Consulta E: Obtener el cliente asociado a una cuenta
    def get_client_by_account(self, account_ref: str) -> dict[str, Any] | None:
        query = """
        MATCH (c:Cliente)-[:TIENE_CUENTA]->(cu:Cuenta)
        WHERE cu.cuentaId = $account_ref OR cu.nro = $account_ref
        RETURN c
        """
        with self._driver.session() as session:
            res = session.run(query, account_ref=str(account_ref)).single()
            return dict(res["c"]) if res else None

    # Consulta F: Obtener cliente y sus cuentas mediante la relación TIENE_CUENTA
    def get_graph_clients_and_accounts(self) -> list[dict[str, Any]]:
        query = """
        MATCH (c:Cliente)-[r:TIENE_CUENTA]->(cu:Cuenta)
        RETURN c.clienteId AS clienteId,
               c.nombres AS nombres,
               c.apellidos AS apellidos,
               type(r) AS relacion,
               cu.cuentaId AS cuentaId,
               cu.saldoUSD AS saldoUSD,
               cu.saldoBs AS saldoBs,
               cu.estado AS estado
        ORDER BY c.clienteId, cu.cuentaId
        """
        with self._driver.session() as session:
            return [record.data() for record in session.run(query)]

    # Consulta G: Consultar información necesaria para una futura conversión monetaria
    def get_pending_accounts(self) -> list[dict[str, Any]]:
        query = """
        MATCH (cu:Cuenta)
        WHERE cu.estado = 'PENDIENTE' OR cu.estado IS NULL
        RETURN cu.cuentaId AS cuentaId,
               cu.nro AS nro,
               cu.bancoId AS bancoId,
               cu.saldoUSD AS saldoUSD,
               cu.saldo AS saldo
        ORDER BY cu.cuentaId
        """
        with self._driver.session() as session:
            return [record.data() for record in session.run(query)]

    # Consulta H: Actualizar los datos de una cuenta (Confirmación de Transacción)

    def encrypted_accounts_after(self, after, limit):
        query="""
        MATCH (cu:Cuenta) WHERE cu.cuentaId > $after
        RETURN cu.cuentaId AS Nro,cu.identificacion AS Identificacion,
               cu.nombres AS Nombres,cu.apellidos AS Apellidos,cu.nro_cuenta AS NroCuenta,
               cu.id_banco AS IdBanco,cu.saldo AS Saldo
        ORDER BY cu.cuentaId LIMIT $limit
        """
        with self._driver.session() as session:
            return session.run(query,after=after,limit=limit).data()

    def encrypted_accounts(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Devuelve las cuentas formateadas para el router bancario y el barrido de ASFI."""
        query = """
        MATCH (cliente:Cliente)-[:TIENE_CUENTA]->(cuenta:Cuenta)
        RETURN cuenta.nro AS Nro,
               cuenta.cuentaId AS CuentaId,
               cuenta.identificacion AS Identificacion,
               cuenta.nombres AS Nombres,
               cuenta.apellidos AS Apellidos,
               cuenta.nro_cuenta AS NroCuenta,
               cuenta.id_banco AS IdBanco,
               cuenta.bancoId AS BancoId,
               cuenta.saldo AS Saldo,
               cuenta.saldoUSD AS SaldoUSD,
               cuenta.saldo_bs AS SaldoBs,
               cuenta.estado AS Estado,
               cuenta.codigo_verificacion AS CodigoVerificacion,
               cuenta.convertido_at AS FechaConversion
        ORDER BY cuenta.nro SKIP $offset LIMIT $limit
        """
        with self._driver.session() as session:
            return [record.data() for record in session.run(query, offset=offset, limit=limit)]

    def count_accounts(self) -> int:
        with self._driver.session() as session:
            res = session.run("MATCH (cu:Cuenta) RETURN count(cu) AS total").single()
            return int(res["total"]) if res else 0

    def count_clients(self) -> int:
        with self._driver.session() as session:
            res = session.run("MATCH (c:Cliente) RETURN count(c) AS total").single()
            return int(res["total"]) if res else 0

    def count_relationships(self) -> int:
        with self._driver.session() as session:
            res = session.run("MATCH ()-[r:TIENE_CUENTA]->() RETURN count(r) AS total").single()
            return int(res["total"]) if res else 0

    def health_check(self) -> dict[str, Any]:
        try:
            self._driver.verify_connectivity()
            return {
                "neo4j": "connected",
                "url": self._url,
                "clientes_total": self.count_clients(),
                "cuentas_total": self.count_accounts(),
                "relaciones_total": self.count_relationships(),
            }
        except Exception as error:
            return {"neo4j": "disconnected", "error": str(error)}

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

