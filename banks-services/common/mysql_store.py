"""Adaptador MySQL para el contrato común de los servicios bancarios."""
from __future__ import annotations

import threading
from typing import Any

import pymysql

from common.bank_router import ConfirmationRequest


class MySQLStore:
    def __init__(self, url: str):
        self._connection = self._connect(url)
        self._lock = threading.Lock()
        self._create_schema()

    @staticmethod
    def _connect(url: str):
        prefix = "mysql://"
        if not url.startswith(prefix):
            raise ValueError("DATABASE_URL de MySQL debe comenzar con mysql://")
        credentials, database = url[len(prefix):].split("/", 1)
        user_password, host_port = credentials.rsplit("@", 1)
        user, password = user_password.split(":", 1)
        if ":" in host_port:
            host, port = host_port.split(":", 1)
        else:
            host, port = host_port, "3306"
        return pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _create_schema(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    nro VARCHAR(255) PRIMARY KEY,
                    identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL,
                    nro_cuenta TEXT NOT NULL,
                    id_banco INT NOT NULL,
                    saldo TEXT NOT NULL,
                    saldo_bs TEXT,
                    codigo_verificacion CHAR(8),
                    tipo_cambio TEXT,
                    convertido_at DATETIME(6)
                )
                """
            )
        self._connection.commit()

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT nro AS Nro, identificacion AS Identificacion,
                       nombres AS Nombres, apellidos AS Apellidos,
                       nro_cuenta AS NroCuenta, id_banco AS IdBanco,
                       saldo AS Saldo
                FROM cuentas ORDER BY nro LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return list(cursor.fetchall())

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        with self._lock:
            try:
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE cuentas
                        SET saldo_bs=%s, codigo_verificacion=%s,
                            tipo_cambio=%s, convertido_at=%s
                        WHERE nro=%s
                        """,
                        (
                            request.saldo_bs,
                            request.verification_code.upper(),
                            request.exchange_rate,
                            request.converted_at.replace(tzinfo=None),
                            request.account_ref,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError("Cuenta no encontrada")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

        return {
            "account_ref": request.account_ref,
            "verification_code": request.verification_code.upper(),
            "status": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def upsert_account(self, record: dict[str, Any]) -> None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cuentas
                    (nro, identificacion, nombres, apellidos, nro_cuenta,
                     id_banco, saldo)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                    identificacion=VALUES(identificacion),
                    nombres=VALUES(nombres), apellidos=VALUES(apellidos),
                    nro_cuenta=VALUES(nro_cuenta), id_banco=VALUES(id_banco),
                    saldo=VALUES(saldo)
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
            self._connection.commit()
