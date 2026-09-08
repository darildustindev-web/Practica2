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


class Neo4jStore:
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
    def upsert_account(self, record: dict[str, Any]) -> None:
        """Inserta o actualiza un registro en el grafo con MERGE idempotente.
        
        Crea (:Cliente), (:Cuenta) y la relación (:Cliente)-[:TIENE_CUENTA]->(:Cuenta).
        """
        cuenta_id = str(record.get("Nro") or record.get("CuentaId") or record.get("cuenta_id", "")).strip()
        identificacion = str(record.get("Identificacion") or record.get("identificacion", "")).strip()
        nombres = str(record.get("Nombres") or record.get("nombres", "")).strip()
        apellidos = str(record.get("Apellidos") or record.get("apellidos", "")).strip()
        nro_cuenta = str(record.get("NroCuenta") or record.get("nro_cuenta", "")).strip()
        id_banco = int(record.get("IdBanco") or record.get("BancoId") or record.get("banco_id", 13))
        saldo = str(record.get("Saldo") or record.get("SaldoUSD") or record.get("saldo_usd", "")).strip()
        estado = str(record.get("Estado") or record.get("estado", "PENDIENTE")).strip()

        query = """
        MERGE (cliente:Cliente {clienteId: $identificacion})
        ON CREATE SET
            cliente.identificacion = $identificacion,
            cliente.nombres = $nombres,
            cliente.apellidos = $apellidos
        ON MATCH SET
            cliente.nombres = $nombres,
            cliente.apellidos = $apellidos

        MERGE (cuenta:Cuenta {cuentaId: $cuenta_id})
        ON CREATE SET
            cuenta.nro = $cuenta_id,
            cuenta.cuentaId = $cuenta_id,
            cuenta.bancoId = $id_banco,
            cuenta.id_banco = $id_banco,
            cuenta.saldo = $saldo,
            cuenta.saldoUSD = $saldo,
            cuenta.saldoBs = null,
            cuenta.saldo_bs = null,
            cuenta.estado = $estado,
            cuenta.codigoVerificacion = null,
            cuenta.codigo_verificacion = null,
            cuenta.fechaConversion = null,
            cuenta.convertido_at = null,
            cuenta.tipoCambio = null,
            cuenta.tipo_cambio = null,
            cuenta.nroCuenta = $nro_cuenta,
            cuenta.nro_cuenta = $nro_cuenta,
            cuenta.identificacion = $identificacion,
            cuenta.nombres = $nombres,
            cuenta.apellidos = $apellidos
        ON MATCH SET
            cuenta.saldo = $saldo,
            cuenta.saldoUSD = $saldo,
            cuenta.nroCuenta = $nro_cuenta,
            cuenta.nro_cuenta = $nro_cuenta

        MERGE (cliente)-[:TIENE_CUENTA]->(cuenta)
        """
        with self._driver.session() as session:
            session.run(
                query,
                cuenta_id=cuenta_id,
                identificacion=identificacion,
                nombres=nombres,
                apellidos=apellidos,
                nro_cuenta=nro_cuenta,
                id_banco=id_banco,
                saldo=saldo,
                estado=estado,
            ).consume()

    # =========================================================================
    # 8 Consultas Cypher Parametrizadas Requeridas
    # =========================================================================

    # Consulta A: Obtener todos los clientes
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
    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        """Confirma una transacción en la cuenta bancaria aplicando reglas de negocio estrictas."""
        code = request.verification_code.strip().upper()

        # Validación 1: Exactamente 8 caracteres hexadecimales
        if not HEX_CODE_REGEX.fullmatch(code):
            raise ValueError(
                f"El código de verificación '{request.verification_code}' debe contener "
                f"exactamente 8 caracteres hexadecimales (0-9, A-F)."
            )

        ref = str(request.account_ref).strip()

        # Buscar la cuenta actual
        existing = self.get_account_by_id(ref)
        if not existing:
            raise KeyError(f"Cuenta no encontrada: {ref}")

        # Validación 2: Idempotencia y protección anti-replay
        current_state = str(existing.get("estado", "")).upper()
        current_code = str(existing.get("codigoVerificacion") or existing.get("codigo_verificacion") or "").upper()

        if current_state == "CONFIRMADA":
            if current_code == code:
                # Reintento idéntico: respuesta idempotente exitosa (200 OK)
                return {
                    "account_ref": ref,
                    "verification_code": code,
                    "status": "CONFIRMADA",
                    "converted_at": existing.get("fechaConversion") or request.converted_at,
                    "message": "Transacción confirmada previamente (idempotente)",
                }
            # Conflicto anti-replay: intento de reutilización con código diferente (409 Conflict)
            raise ValueError(
                f"Conflicto anti-replay: La cuenta '{ref}' ya fue confirmada previamente "
                f"con un código diferente ('{current_code}'). Transacción rechazada."
            )

        # Actualización de la cuenta
        query_update = """
        MATCH (cu:Cuenta)
        WHERE cu.cuentaId = $account_ref OR cu.nro = $account_ref
        SET cu.saldoBs = $saldo_bs,
            cu.saldo_bs = $saldo_bs,
            cu.codigoVerificacion = $codigo,
            cu.codigo_verificacion = $codigo,
            cu.tipoCambio = $tipo_cambio,
            cu.tipo_cambio = $tipo_cambio,
            cu.fechaConversion = $convertido_at,
            cu.convertido_at = $convertido_at,
            cu.estado = 'CONFIRMADA'
        RETURN cu.cuentaId AS cuentaId, cu.estado AS estado
        """
        with self._driver.session() as session:
            result = session.run(
                query_update,
                account_ref=ref,
                saldo_bs=str(request.saldo_bs),
                codigo=code,
                tipo_cambio=str(request.exchange_rate),
                convertido_at=request.converted_at.isoformat(),
            ).single()

        if not result:
            raise KeyError(f"No se pudo actualizar la cuenta: {ref}")

        return {
            "account_ref": ref,
            "verification_code": code,
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    # =========================================================================
    # Métodos Estándar para Integración con Router y ASFI
    # =========================================================================
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

