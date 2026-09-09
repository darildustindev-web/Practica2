"""Adaptador MongoDB para el contrato común de los servicios bancarios con soporte NoSQL avanzado y caché Redis."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any
from urllib.parse import urlparse

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from redis import Redis

from common.bank_router import ConfirmationRequest

logger = logging.getLogger(__name__)

HEX_CODE_PATTERN = re.compile(r"^[0-9A-Fa-f]{8}$")


from common.nosql_bulk import NoSQLBulk

class MongoStore(NoSQLBulk):
    def __init__(
        self,
        url: str,
        bank_id: int | None = None,
        redis_url: str | None = None,
    ):
        prefix = "mongodb://"
        if not url.startswith(prefix) and not url.startswith("mongodb+srv://"):
            raise ValueError("DATABASE_URL de MongoDB debe comenzar con mongodb:// o mongodb+srv://")

        self._bank_id = bank_id if bank_id is not None else int(os.getenv("BANK_ID", "0"))
        self._client = MongoClient(url, serverSelectionTimeoutMS=5000)

        # Extraer nombre de base de datos de la URL de forma segura
        parsed = urlparse(url)
        path = parsed.path.lstrip("/").split("?")[0]
        database_name = path if path else (f"bank_{self._bank_id:02d}" if self._bank_id else "bank_default")

        self._db_name = database_name
        self._database = self._client[database_name]
        self._collection = self._database["cuentas"]
        self._lock = threading.Lock()

        # Índices requeridos para rendimiento y aislamiento de cuentas
        try:
            self._collection.create_index("nro", unique=True)
            self._collection.create_index("id_banco")
            self._collection.create_index("codigo_verificacion")
        except PyMongoError as error:
            logger.warning("No se pudieron crear índices en MongoDB (%s): %s", database_name, error)

        # Conexión opcional a Redis para caché y trazabilidad rápida de transacciones
        redis_target_url = redis_url or os.getenv("REDIS_URL")
        self._redis: Redis | None = None
        self._redis_prefix = f"bank:{self._bank_id if self._bank_id else database_name}"

        if redis_target_url:
            try:
                parsed_redis = urlparse(redis_target_url)
                if parsed_redis.scheme == "redis" and parsed_redis.hostname:
                    self._redis = Redis(
                        host=parsed_redis.hostname,
                        port=parsed_redis.port or 6379,
                        db=int(parsed_redis.path.lstrip("/") or 0),
                        decode_responses=True,
                        socket_timeout=2.0,
                    )
                    self._redis.ping()
            except Exception as error:
                logger.warning("Redis no disponible para MongoStore (%s): %s", database_name, error)
                self._redis = None

    @property
    def bank_id(self) -> int:
        return self._bank_id

    @property
    def db_name(self) -> str:
        return self._db_name

    def count_accounts(self) -> int:
        """Retorna el número total de cuentas de este banco en MongoDB."""
        filter_query: dict[str, Any] = {}
        if self._bank_id > 0:
            filter_query["id_banco"] = self._bank_id
        return self._collection.count_documents(filter_query)

    def get_account(self, account_ref: str) -> dict[str, Any] | None:
        """Obtiene una cuenta específica por su referencia / CuentaId."""
        filter_query: dict[str, Any] = {"nro": str(account_ref)}
        if self._bank_id > 0:
            filter_query["id_banco"] = self._bank_id

        record = self._collection.find_one(filter_query, {"_id": 0})
        if not record:
            return None
        return self._to_api_record(record)

    def encrypted_accounts_after(self, after, limit):
        query={'nro':{'$gt':after}}
        if self._bank_id>0:query['id_banco']=self._bank_id
        return [self._to_api_record(r) for r in self._collection.find(query,{'_id':0}).sort('nro',1).limit(limit)]

    def encrypted_accounts(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Consulta paginada de cuentas cifradas garantizando aislamiento por banco."""
        filter_query: dict[str, Any] = {}
        if self._bank_id > 0:
            filter_query["id_banco"] = self._bank_id

        projection = {"_id": 0}
        try:
            cursor = (
                self._collection.find(filter_query, projection)
                .sort("nro", 1)
                .skip(offset)
                .limit(limit)
            )
            return [self._to_api_record(record) for record in cursor]
        except PyMongoError as error:
            logger.error("Error al consultar cuentas en MongoDB (%s): %s", self._db_name, error)
            raise ConnectionError(f"Error de conexión a MongoDB: {error}") from error


    def upsert_accounts_batch(self, records):
        from pymongo import UpdateOne
        operations = []
        for r in records:
            document = dict(nro=str(r['Nro']), id_banco=int(r['IdBanco']),
                            identificacion=r['Identificacion'], nombres=r['Nombres'], apellidos=r['Apellidos'],
                            nro_cuenta=r['NroCuenta'], saldo=r['Saldo'], estado='PENDIENTE')
            operations.append(UpdateOne({'nro': document['nro']}, {'$setOnInsert':document}, upsert=True))
        if operations:
            self._collection.bulk_write(operations, ordered=False)

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])


    def health_check(self) -> dict[str, Any]:
        """Comprueba estado de conexión a MongoDB y Redis."""
        mongo_ok = False
        redis_ok = False
        try:
            self._client.admin.command("ping")
            mongo_ok = True
        except Exception:
            mongo_ok = False

        if self._redis:
            try:
                self._redis.ping()
                redis_ok = True
            except Exception:
                redis_ok = False

        return {
            "mongo_connected": mongo_ok,
            "database": self._db_name,
            "redis_connected": redis_ok,
            "redis_prefix": self._redis_prefix if self._redis else None,
        }

    @staticmethod
    def _to_api_record(record: dict[str, Any]) -> dict[str, Any]:
        """Mapea documento de MongoDB a formato compatible con ASFI y la práctica."""
        nro = str(record.get("nro", ""))
        id_banco = int(record.get("id_banco", 0))
        saldo_usd = str(record.get("saldo", ""))
        saldo_bs = record.get("saldo_bs")
        estado = record.get("estado", "PENDIENTE" if not record.get("codigo_verificacion") else "CONFIRMADA")

        return {
            "Nro": nro,
            "CuentaId": nro,
            "Identificacion": record.get("identificacion", ""),
            "Nombres": record.get("nombres", ""),
            "Apellidos": record.get("apellidos", ""),
            "NroCuenta": record.get("nro_cuenta", ""),
            "IdBanco": id_banco,
            "BancoId": id_banco,
            "Saldo": saldo_usd,
            "SaldoUSD": saldo_usd,
            "SaldoBs": saldo_bs,
            "Estado": estado,
            "CodigoVerificacion": record.get("codigo_verificacion"),
            "FechaConversion": record.get("convertido_at"),
            "TipoCambio": record.get("tipo_cambio"),
        }

