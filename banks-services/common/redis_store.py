"""Adaptador Redis para el contrato común de los servicios bancarios."""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any
from urllib.parse import urlparse

from redis import Redis
from redis.exceptions import RedisError

from common.bank_router import ConfirmationRequest

logger = logging.getLogger(__name__)

HEX_CODE_PATTERN = re.compile(r"^[0-9A-Fa-f]{8}$")


from common.nosql_bulk import NoSQLBulk

class RedisStore(NoSQLBulk):
    def __init__(self, url: str, bank_id: int | None = None):
        parsed = urlparse(url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("DATABASE_URL de Redis debe usar redis://")

        self._bank_id = bank_id if bank_id is not None else int(os.getenv("BANK_ID", "0"))
        self._redis = Redis(
            host=parsed.hostname,
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0),
            decode_responses=True,
            socket_timeout=3.0,
        )

        fragment = parsed.fragment.strip()
        if self._bank_id > 0:
            self._prefix = f"bank:{self._bank_id}"
        elif fragment:
            self._prefix = f"bank:{fragment.removeprefix('bank')}"
        else:
            self._prefix = "bank:default"


        self._lock = threading.Lock()
        self._redis.ping()

    @property
    def bank_id(self) -> int:
        return self._bank_id

    @property
    def prefix(self) -> str:
        return self._prefix

    def _key(self, account_ref: str) -> str:
        return f"{self._prefix}:cuenta:{account_ref}"

    def _tx_key(self, account_ref: str) -> str:
        return f"{self._prefix}:tx:{account_ref}"

    def count_accounts(self) -> int:
        """Retorna el número de cuentas almacenadas en Redis bajo este namespace."""
        return self._redis.zcard(f'{self._prefix}:index')

    def get_account(self, account_ref: str) -> dict[str, Any] | None:
        """Obtiene una cuenta específica por referencia en Redis."""
        key = self._key(account_ref)
        record = self._redis.hgetall(key)
        if not record:
            return None
        return self._to_api_record(record)

    def encrypted_accounts_after(self, after, limit):
        refs=self._redis.zrangebylex(f'{self._prefix}:index','('+after,'+',start=0,num=limit)
        with self._redis.pipeline(transaction=False) as pipe:
            for ref in refs:pipe.hgetall(self._key(ref))
            return [self._to_api_record(r) for r in pipe.execute() if r]

    def encrypted_accounts(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Obtiene cuentas cifradas garantizando aislamiento por namespace de banco."""
        try:
            refs = self._redis.zrange(f'{self._prefix}:index', offset, offset + limit - 1)
            with self._redis.pipeline(transaction=False) as pipe:
                for ref in refs:
                    pipe.hgetall(self._key(ref))
                return [self._to_api_record(r) for r in pipe.execute() if r]
        except RedisError as error:
            logger.error("Error al consultar cuentas en Redis (%s): %s", self._prefix, error)
            raise ConnectionError(f"Error de conexión a Redis: {error}") from error


    def upsert_accounts_batch(self, records):
        # Script atómico: una recarga nunca borra una confirmación existente.
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then
            redis.call('HSET', KEYS[1], unpack(ARGV, 2))
        end
        redis.call('ZADD', KEYS[2], 0, ARGV[1])
        return 1
        """
        with self._redis.pipeline(transaction=False) as pipe:
            for r in records:
                ref = str(r['Nro'])
                values = dict(nro=ref,id_banco=str(r['IdBanco']),identificacion=r['Identificacion'],
                              nombres=r['Nombres'],apellidos=r['Apellidos'],nro_cuenta=r['NroCuenta'],
                              saldo=r['Saldo'],estado='PENDIENTE')
                args = [part for pair in values.items() for part in pair]
                pipe.eval(script,2,self._key(ref),f'{self._prefix}:index',ref,*args)
            pipe.execute()

    def upsert_account(self, record):
        self.upsert_accounts_batch([record])


    def health_check(self) -> dict[str, Any]:
        """Comprueba estado de conexión a Redis."""
        try:
            self._redis.ping()
            connected = True
        except Exception:
            connected = False
        return {
            "redis_connected": connected,
            "prefix": self._prefix,
        }

    @staticmethod
    def _to_api_record(record: dict[str, Any]) -> dict[str, Any]:
        """Mapea registro de Redis al formato API."""
        nro = str(record.get("nro", ""))
        id_banco = int(record.get("id_banco", 0))
        saldo_usd = str(record.get("saldo", ""))
        saldo_bs = record.get("saldo_bs") or None
        codigo_verificacion = record.get("codigo_verificacion") or None
        estado = record.get("estado", "CONFIRMADA" if codigo_verificacion else "PENDIENTE")

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
            "CodigoVerificacion": codigo_verificacion,
            "FechaConversion": record.get("convertido_at") or None,
            "TipoCambio": record.get("tipo_cambio") or None,
        }

