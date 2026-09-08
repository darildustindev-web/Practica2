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


class RedisStore:
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
            self._prefix = f"bank:{fragment}"
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
        keys = list(self._redis.scan_iter(match=f"{self._prefix}:cuenta:*"))
        return len(keys)

    def get_account(self, account_ref: str) -> dict[str, Any] | None:
        """Obtiene una cuenta específica por referencia en Redis."""
        key = self._key(account_ref)
        record = self._redis.hgetall(key)
        if not record:
            return None
        return self._to_api_record(record)

    def encrypted_accounts(self, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Obtiene cuentas cifradas garantizando aislamiento por namespace de banco."""
        try:
            keys = sorted(
                self._redis.scan_iter(match=f"{self._prefix}:cuenta:*"),
                key=lambda k: int(k.rsplit(":", 1)[-1]) if k.rsplit(":", 1)[-1].isdigit() else k,
            )
            records = []
            for key in keys[offset:offset + limit]:
                record = self._redis.hgetall(key)
                if record:
                    records.append(self._to_api_record(record))
            return records
        except RedisError as error:
            logger.error("Error al consultar cuentas en Redis (%s): %s", self._prefix, error)
            raise ConnectionError(f"Error de conexión a Redis: {error}") from error

    def confirm(self, request: ConfirmationRequest) -> dict[str, Any]:
        """Confirma una transacción en Redis validando código hex de 8 caracteres y control anti-repetición."""
        verification_code = request.verification_code.strip().upper()
        if not HEX_CODE_PATTERN.fullmatch(verification_code):
            raise ValueError("El código de verificación debe contener exactamente 8 caracteres hexadecimales (0-9, A-F)")

        with self._lock:
            key = self._key(request.account_ref)
            if not self._redis.exists(key):
                raise KeyError(f"Cuenta '{request.account_ref}' no encontrada en el banco {self._bank_id}")

            existing = self._redis.hgetall(key)
            existing_code = existing.get("codigo_verificacion")

            # Control de transacciones / prevención de reutilización y alteración
            if existing_code:
                if existing_code == verification_code:
                    return {
                        "account_ref": request.account_ref,
                        "cuenta_id": request.account_ref,
                        "banco_id": self._bank_id,
                        "verification_code": verification_code,
                        "codigo_verificacion": verification_code,
                        "saldo_bs": existing.get("saldo_bs", request.saldo_bs),
                        "tipo_cambio": existing.get("tipo_cambio", request.exchange_rate),
                        "status": "CONFIRMADA",
                        "estado": "CONFIRMADA",
                        "converted_at": request.converted_at,
                        "reintento": True,
                    }
                else:
                    raise ValueError(
                        f"Operación rechazada: La cuenta '{request.account_ref}' ya fue confirmada previamente "
                        f"con el código de verificación '{existing_code}'."
                    )

            # Actualizar estado y saldo en Redis
            update_data = {
                "saldo_bs": request.saldo_bs,
                "codigo_verificacion": verification_code,
                "tipo_cambio": request.exchange_rate,
                "convertido_at": request.converted_at.isoformat(),
                "estado": "CONFIRMADA",
            }
            self._redis.hset(key, mapping=update_data)

            # Registrar transacción
            self._redis.hset(
                self._tx_key(request.account_ref),
                mapping={
                    "account_ref": request.account_ref,
                    "verification_code": verification_code,
                    "saldo_bs": request.saldo_bs,
                    "tipo_cambio": request.exchange_rate,
                    "estado": "CONFIRMADA",
                    "convertido_at": request.converted_at.isoformat(),
                },
            )

        return {
            "account_ref": request.account_ref,
            "cuenta_id": request.account_ref,
            "banco_id": self._bank_id,
            "verification_code": verification_code,
            "codigo_verificacion": verification_code,
            "saldo_bs": request.saldo_bs,
            "tipo_cambio": request.exchange_rate,
            "status": "CONFIRMADA",
            "estado": "CONFIRMADA",
            "converted_at": request.converted_at,
        }

    def upsert_account(self, record: dict[str, Any]) -> None:
        """Almacena o actualiza una cuenta en Redis."""
        nro = str(record.get("Nro") or record.get("CuentaId") or record.get("nro"))
        id_banco = str(int(record.get("IdBanco") or record.get("BancoId") or record.get("id_banco", self._bank_id)))

        account = {
            "nro": nro,
            "cuenta_id": nro,
            "identificacion": record.get("Identificacion") or record.get("identificacion", ""),
            "nombres": record.get("Nombres") or record.get("nombres", ""),
            "apellidos": record.get("Apellidos") or record.get("apellidos", ""),
            "nro_cuenta": record.get("NroCuenta") or record.get("nro_cuenta", ""),
            "id_banco": id_banco,
            "banco_id": id_banco,
            "saldo": record.get("Saldo") or record.get("SaldoUSD") or record.get("saldo", ""),
            "saldo_usd": record.get("SaldoUSD") or record.get("Saldo") or record.get("saldo", ""),
            "saldo_bs": str(record.get("SaldoBs") or record.get("saldo_bs") or ""),
            "estado": record.get("Estado") or record.get("estado", "PENDIENTE"),
            "codigo_verificacion": str(record.get("CodigoVerificacion") or record.get("codigo_verificacion") or ""),
            "tipo_cambio": str(record.get("TipoCambio") or record.get("tipo_cambio") or ""),
            "convertido_at": str(record.get("FechaConversion") or record.get("convertido_at") or ""),
        }

        with self._lock:
            self._redis.hset(self._key(nro), mapping=account)

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

