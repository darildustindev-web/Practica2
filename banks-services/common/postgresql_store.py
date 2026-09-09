"""Adaptador PostgreSQL para el contrato común de los servicios bancarios."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from common.bank_router import ConfirmationRequest


class PostgreSQLStore:
    def __init__(self, dsn: str):
        self._connection = psycopg2.connect(dsn)
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection, self._connection.cursor() as cursor:
            cursor.execute(
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
                    codigo_verificacion CHAR(8),
                    tipo_cambio TEXT,
                    convertido_at TIMESTAMPTZ
                )
                """
            )

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT nro AS "Nro",
                       identificacion AS "Identificacion",
                       nombres AS "Nombres",
                       apellidos AS "Apellidos",
                       nro_cuenta AS "NroCuenta",
                       id_banco AS "IdBanco",
                       saldo AS "Saldo"
                FROM cuentas
                ORDER BY nro
                OFFSET %s LIMIT %s
                """,
                (offset, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock, self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE cuentas
                    SET saldo_bs = %s,
                        codigo_verificacion = %s,
                        tipo_cambio = %s,
                        convertido_at = %s
                    WHERE nro = %s
                    """,
                    (
                        request.saldo_bs,
                        request.verification_code.upper(),
                        request.exchange_rate,
                        request.converted_at,
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

    def confirm_batch(self, requests: list[ConfirmationRequest]) -> list[dict[str, Any]]:
        if not requests:
            return []
        query = """
        UPDATE cuentas
        SET saldo_bs = %s,
            codigo_verificacion = %s,
            tipo_cambio = %s,
            convertido_at = %s
        WHERE nro = %s
        """
        params = [
            (
                r.saldo_bs,
                r.verification_code.upper(),
                r.exchange_rate,
                r.converted_at,
                r.account_ref,
            )
            for r in requests
        ]
        from psycopg2.extras import execute_batch
        with self._lock, self._connection:
            with self._connection.cursor() as cursor:
                execute_batch(cursor, query, params, page_size=1000)
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
        INSERT INTO cuentas
            (nro, identificacion, nombres, apellidos,
             nro_cuenta, id_banco, saldo)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (nro) DO UPDATE SET
            identificacion = EXCLUDED.identificacion,
            nombres = EXCLUDED.nombres,
            apellidos = EXCLUDED.apellidos,
            nro_cuenta = EXCLUDED.nro_cuenta,
            id_banco = EXCLUDED.id_banco,
            saldo = EXCLUDED.saldo
        """
        params = [
            (
                str(r["Nro"]),
                r["Identificacion"],
                r["Nombres"],
                r["Apellidos"],
                r["NroCuenta"],
                int(r["IdBanco"]),
                r["Saldo"],
            )
            for r in records
        ]
        from psycopg2.extras import execute_batch
        with self._lock, self._connection:
            with self._connection.cursor() as cursor:
                execute_batch(cursor, query, params, page_size=1000)
