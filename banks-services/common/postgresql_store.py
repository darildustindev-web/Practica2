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


class PostgreSQLStore:
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

    def upsert_account(self, record: dict[str, Any]) -> None:
        nro = str(record["Nro"])
        with self._lock, self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO clientes (nro, identificacion, nombres, apellidos)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (nro) DO UPDATE SET
                        identificacion = EXCLUDED.identificacion,
                        nombres = EXCLUDED.nombres,
                        apellidos = EXCLUDED.apellidos
                    """,
                    (
                        nro,
                        record["Identificacion"],
                        record["Nombres"],
                        record["Apellidos"],
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO cuentas
                        (nro, cliente_nro, nro_cuenta, id_banco, saldo)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (nro) DO UPDATE SET
                        cliente_nro = EXCLUDED.cliente_nro,
                        nro_cuenta = EXCLUDED.nro_cuenta,
                        id_banco = EXCLUDED.id_banco,
                        saldo = EXCLUDED.saldo
                    """,
                    (
                        nro,
                        nro,
                        record["NroCuenta"],
                        int(record["IdBanco"]),
                        record["Saldo"],
                    ),
                )
