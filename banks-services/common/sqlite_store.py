"""Adaptador SQLite para el contrato común de los servicios bancarios."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from common.bank_router import ConfirmationRequest


class SQLiteStore:
    def __init__(self, database_url: str):
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("DATABASE_URL de SQLite debe comenzar con sqlite:///")
        self._connection = sqlite3.connect(
            Path(database_url[len(prefix):]).expanduser(),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    nro TEXT PRIMARY KEY,
                    identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
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

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT nro AS Nro, identificacion AS Identificacion,
                       nombres AS Nombres, apellidos AS Apellidos,
                       nro_cuenta AS NroCuenta, id_banco AS IdBanco,
                       saldo AS Saldo
                FROM cuentas ORDER BY nro LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE cuentas
                SET saldo_bs = ?, codigo_verificacion = ?,
                    tipo_cambio = ?, convertido_at = ?
                WHERE nro = ?
                """,
                (
                    request.saldo_bs,
                    request.verification_code.upper(),
                    request.exchange_rate,
                    request.converted_at.isoformat(),
                    request.account_ref,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("Cuenta no encontrada")
        return {
            "account_ref": request.account_ref,
            "verification_code": request.verification_code.upper(),
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def upsert_account(self, record: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO cuentas
                    (nro, identificacion, nombres, apellidos,
                     nro_cuenta, id_banco, saldo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nro) DO UPDATE SET
                    identificacion = excluded.identificacion,
                    nombres = excluded.nombres,
                    apellidos = excluded.apellidos,
                    nro_cuenta = excluded.nro_cuenta,
                    id_banco = excluded.id_banco,
                    saldo = excluded.saldo
                """,
                (
                    str(record["Nro"]),
                    record["Identificacion"],
                    record["Nombres"],
                    record["Apellidos"],
                    record["NroCuenta"],
                    int(record["IdBanco"]),
                    record["Saldo"],
                ),
            )
