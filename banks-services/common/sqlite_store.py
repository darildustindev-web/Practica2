"""Adaptador SQLite para el contrato común de los servicios bancarios.

Esquema normalizado (Integrante 2): se separan los datos del cliente
(`clientes`) de los datos de la cuenta (`cuentas`), enlazados por
`cliente_nro`, tal como lo pide la tarjeta de Trello de Bancos Relacionales
("Tablas en bancos: Clientes, Cuentas"). El contrato HTTP/JSON expuesto por
`encrypted_accounts()`/`confirm()` no cambia: se arma con un JOIN para que
ASFI y el resto del equipo no tengan que modificar nada.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from common.bank_router import ConfirmationRequest


from common.relational_bulk import RelationalBulk


class SQLiteStore(RelationalBulk):
    def __init__(self, database_url: str):
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("DATABASE_URL de SQLite debe comenzar con sqlite:///")
        self._connection = sqlite3.connect(
            Path(database_url[len(prefix):]).expanduser(),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS clientes (
                    nro TEXT PRIMARY KEY,
                    identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    nro TEXT PRIMARY KEY,
                    cliente_nro TEXT NOT NULL REFERENCES clientes(nro),
                    nro_cuenta TEXT NOT NULL,
                    id_banco INTEGER NOT NULL,
                    saldo TEXT NOT NULL,
                    saldo_bs TEXT,
                    codigo_verificacion TEXT,
                    tipo_cambio TEXT,
                    convertido_at TEXT
                )
                """
            )
            cursor = self._connection.cursor()
            self.migrate_legacy_schema(cursor)
            cursor.close()
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cuentas_cliente ON cuentas(cliente_nro)"
            )

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT c.nro AS Nro,
                       cl.identificacion AS Identificacion,
                       cl.nombres AS Nombres,
                       cl.apellidos AS Apellidos,
                       c.nro_cuenta AS NroCuenta,
                       c.id_banco AS IdBanco,
                       c.saldo AS Saldo
                FROM cuentas c
                JOIN clientes cl ON cl.nro = c.cliente_nro
                ORDER BY c.nro
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])
