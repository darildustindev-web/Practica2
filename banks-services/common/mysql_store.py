"""Adaptador MySQL para el contrato común de los servicios bancarios.

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

import pymysql

from common.bank_router import ConfirmationRequest


from common.relational_bulk import RelationalBulk


class MySQLStore(RelationalBulk):
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
                CREATE TABLE IF NOT EXISTS clientes (
                    nro VARCHAR(255) PRIMARY KEY,
                    identificacion TEXT NOT NULL,
                    nombres TEXT NOT NULL,
                    apellidos TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cuentas (
                    nro VARCHAR(255) PRIMARY KEY,
                    cliente_nro VARCHAR(255) NOT NULL,
                    nro_cuenta TEXT NOT NULL,
                    id_banco INT NOT NULL,
                    saldo TEXT NOT NULL,
                    saldo_bs TEXT,
                    codigo_verificacion CHAR(8),
                    tipo_cambio TEXT,
                    convertido_at DATETIME(6),
                    INDEX idx_cuentas_cliente (cliente_nro),
                    CONSTRAINT fk_cuentas_cliente FOREIGN KEY (cliente_nro)
                        REFERENCES clientes(nro)
                )
                """
            )
            self.migrate_legacy_schema(cursor)
        self._connection.commit()

    def encrypted_accounts(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor() as cursor:
            self._connection.rollback()  # No reutilizar instantáneas REPEATABLE READ entre peticiones.
            cursor.execute(
                """
                SELECT c.nro AS Nro, cl.identificacion AS Identificacion,
                       cl.nombres AS Nombres, cl.apellidos AS Apellidos,
                       c.nro_cuenta AS NroCuenta, c.id_banco AS IdBanco,
                       c.saldo AS Saldo
                FROM cuentas c
                JOIN clientes cl ON cl.nro = c.cliente_nro
                ORDER BY c.nro LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = list(cursor.fetchall())
            self._connection.rollback()
            return rows

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])
