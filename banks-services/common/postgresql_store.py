"""Adaptador PostgreSQL para el contrato común de los servicios bancarios.

Esquema normalizado (Integrante 2): se separan los datos del cliente
(`clientes`) de los datos de la cuenta (`cuentas`), enlazados por
`cliente_nro`, tal como lo pide la tarjeta de Trello de Bancos Relacionales
("Tablas en bancos: Clientes, Cuentas"). El contrato HTTP/JSON expuesto por
`encrypted_accounts()`/`confirm()` no cambia: se arma con un JOIN para que
ASFI y el resto del equipo no tengan que modificar nada.
"""
from __future__ import annotations

import threading
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from common.bank_router import ConfirmationRequest


from common.relational_bulk import RelationalBulk


class PostgreSQLStore(RelationalBulk):
    def __init__(self, dsn: str):
        self._connection = psycopg2.connect(dsn)
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection, self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS clientes (
                    nro TEXT PRIMARY KEY,
                    identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    nro TEXT PRIMARY KEY,
                    cliente_nro TEXT NOT NULL REFERENCES clientes(nro),
                    nro_cuenta TEXT NOT NULL,
                    id_banco INTEGER NOT NULL,
                    saldo TEXT NOT NULL,
                    saldo_bs TEXT,
                    codigo_verificacion CHAR(8),
                    tipo_cambio TEXT,
                    convertido_at TIMESTAMPTZ
                )
                """
            )
            self.migrate_legacy_schema(cursor)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_cuentas_cliente ON cuentas(cliente_nro)"
            )

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT c.nro AS "Nro",
                       cl.identificacion AS "Identificacion",
                       cl.nombres AS "Nombres",
                       cl.apellidos AS "Apellidos",
                       c.nro_cuenta AS "NroCuenta",
                       c.id_banco AS "IdBanco",
                       c.saldo AS "Saldo"
                FROM cuentas c
                JOIN clientes cl ON cl.nro = c.cliente_nro
                ORDER BY c.nro
                OFFSET %s LIMIT %s
                """,
                (offset, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])
