"""Servicio bancario parametrizable para desarrollo local y producción."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status

from common.bank_router import (
    BANK_METADATA,
    ConfirmationRequest,
    JsonBankStore,
    create_bank_router,
)
from common.mongo_store import MongoStore
from common.mysql_store import MySQLStore
from common.neo4j_store import Neo4jStore
from common.postgresql_store import PostgreSQLStore
from common.redis_store import RedisStore
from common.sqlite_store import SQLiteStore

project_root = Path(__file__).resolve().parents[2]


def create_app(
    bank_id: int | None = None,
    storage: str | None = None,
    database_url: str | None = None,
    data_file: Path | None = None,
) -> FastAPI:
    b_id = bank_id if bank_id is not None else int(os.getenv("BANK_ID", "1"))
    if not 1 <= b_id <= 14:
        raise ValueError("BANK_ID debe estar entre 1 y 14")

    st = (storage or os.getenv("BANK_STORAGE", "json")).lower()
    df = data_file or Path(
        os.getenv("BANK_DATA_FILE", str(project_root / "data" / "seed" / f"bank_{b_id:02d}.jsonl"))
    )
    db_url = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    r_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    if st == "json":
        store = JsonBankStore(df, bank_id=b_id)
    elif st == "postgres":
        if not db_url:
            raise ValueError("DATABASE_URL es requerido para storage=postgres")
        store = PostgreSQLStore(db_url)
    elif st == "mysql":
        if not db_url:
            raise ValueError("DATABASE_URL es requerido para storage=mysql")
        store = MySQLStore(db_url)
    elif st == "sqlite":
        if not db_url:
            db_url = f"sqlite:///{project_root}/data/bank_{b_id:02d}.sqlite"
        store = SQLiteStore(db_url)
    elif st == "mongo":
        if not db_url:
            db_url = f"mongodb://127.0.0.1:27017/bank_{b_id:02d}"
        store = MongoStore(db_url, bank_id=b_id, redis_url=r_url)
    elif st == "neo4j":
        if not db_url:
            raise ValueError("DATABASE_URL es requerido para storage=neo4j")
        store = Neo4jStore(db_url)
    elif st == "redis":
        if not db_url:
            db_url = f"redis://127.0.0.1:6379/0#bank{b_id:02d}"
        store = RedisStore(db_url, bank_id=b_id)
    else:
        raise ValueError(f"BANK_STORAGE no soportado: {st}")

    b_meta = BANK_METADATA.get(b_id, {"name": f"Banco {b_id}", "algorithm": "Desconocido"})
    bank_app = FastAPI(
        title=f"Servicio {b_meta['name']} (ID {b_id})",
        description=f"API Bancaria con cifrado {b_meta['algorithm']} y almacenamiento {st.upper()}",
        version="2.0.0",
    )

    bank_app.include_router(create_bank_router(store, b_id))

    # Protección de la comunicación entre nodos (spoofing / MITM / replay).
    # Sólo se activa si existe ASFI_HMAC_SECRET; sin esa variable el
    # servicio se comporta exactamente igual que antes.
    from shared.seguridad import instalar_middleware
    if instalar_middleware(bank_app):
        print(f'[seguridad] Banco {b_id}: firma HMAC entre nodos ACTIVA')

    @bank_app.get("/cuentas", tags=[f"Banco {b_id} - Acceso Directo"])
    def read_accounts_direct(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Obtiene las cuentas cifradas del banco (ruta directa /cuentas)."""
        try:
            cuentas = store.encrypted_accounts(offset, limit)
            total = store.count_accounts() if hasattr(store, "count_accounts") else len(cuentas)
            return {
                "banco_id": b_id,
                "banco_nombre": b_meta["name"],
                "algoritmo": b_meta["algorithm"],
                "offset": offset,
                "limit": limit,
                "total": total,
                "cuentas": cuentas,
            }
        except ConnectionError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @bank_app.post("/confirmar", tags=[f"Banco {b_id} - Acceso Directo"])
    def confirm_account_direct(request: ConfirmationRequest) -> dict[str, Any]:
        """Confirma una transacción en la cuenta (ruta directa /confirmar)."""
        try:
            return store.confirm(request)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ConnectionError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    @bank_app.get("/cuentas/{account_ref}", tags=[f"Banco {b_id} - Acceso Directo"])
    def read_single_account_direct(account_ref: str) -> dict[str, Any]:
        """Consulta una cuenta individual por su referencia o CuentaId."""
        getter = getattr(store, "get_account", None) or getattr(store, "get_account_by_id", None)
        if getter:
            account = getter(account_ref)
            if account:
                formatted_acc = {
                    "Nro": account.get("nro") or account.get("cuentaId") or account.get("Nro") or account_ref,
                    "CuentaId": account.get("cuentaId") or account.get("nro") or account.get("CuentaId") or account_ref,
                    "BancoId": int(account.get("bancoId") or account.get("id_banco") or account.get("BancoId") or b_id),
                    "IdBanco": int(account.get("id_banco") or account.get("bancoId") or account.get("IdBanco") or b_id),
                    "Saldo": account.get("saldo") or account.get("saldoUSD") or account.get("Saldo"),
                    "SaldoUSD": account.get("saldoUSD") or account.get("saldo") or account.get("SaldoUSD"),
                    "SaldoBs": account.get("saldoBs") or account.get("saldo_bs") or account.get("SaldoBs"),
                    "Estado": account.get("estado") or account.get("Estado", "PENDIENTE"),
                    "CodigoVerificacion": (
                        account.get("codigoVerificacion")
                        or account.get("codigo_verificacion")
                        or account.get("CodigoVerificacion")
                    ),
                    "FechaConversion": (
                        account.get("fechaConversion")
                        or account.get("convertido_at")
                        or account.get("FechaConversion")
                    ),
                    "TipoCambio": account.get("tipoCambio") or account.get("tipo_cambio"),
                    "NroCuenta": account.get("nroCuenta") or account.get("nro_cuenta") or account.get("NroCuenta"),
                    "Identificacion": (
                        account.get("identificacion")
                        or account.get("clienteId")
                        or account.get("Identificacion")
                    ),
                    "Nombres": account.get("nombres") or account.get("Nombres"),
                    "Apellidos": account.get("apellidos") or account.get("Apellidos"),
                }
                return {
                    "banco_id": b_id,
                    "banco_nombre": b_meta["name"],
                    "algoritmo": b_meta["algorithm"],
                    "cuenta": formatted_acc,
                }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta '{account_ref}' no encontrada en el banco {b_id}",
        )

    if hasattr(store, "get_all_clients"):
        @bank_app.get("/clientes", tags=[f"Banco {b_id} - Consultas Grafo"])
        def read_clients_direct() -> dict[str, Any]:
            clients = store.get_all_clients()
            return {
                "banco_id": b_id,
                "banco_nombre": b_meta["name"],
                "total_clientes": len(clients),
                "clientes": clients,
            }

        @bank_app.get("/clientes/{client_id}/cuentas", tags=[f"Banco {b_id} - Consultas Grafo"])
        def read_client_accounts_direct(client_id: str) -> dict[str, Any]:
            accounts = store.get_accounts_by_client(client_id)
            return {
                "banco_id": b_id,
                "cliente_id": client_id,
                "total_cuentas": len(accounts),
                "cuentas": accounts,
            }

        @bank_app.get("/cuentas/{account_ref}/cliente", tags=[f"Banco {b_id} - Consultas Grafo"])
        def read_account_client_direct(account_ref: str) -> dict[str, Any]:
            client = store.get_client_by_account(account_ref)
            if client:
                return {"banco_id": b_id, "cuenta_id": account_ref, "cliente": client}
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cliente para cuenta '{account_ref}' no encontrado")

        @bank_app.get("/grafo", tags=[f"Banco {b_id} - Consultas Grafo"])
        def read_graph_direct() -> dict[str, Any]:
            graph = store.get_graph_clients_and_accounts()
            return {
                "banco_id": b_id,
                "banco_nombre": b_meta["name"],
                "total_relaciones": len(graph),
                "relaciones": graph,
            }

    @bank_app.get(f"/api/bancos/{b_id}/cuentas", tags=[f"Banco {b_id} - Ruta REST"])
    def read_accounts_by_bank_path(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Obtiene cuentas en la ruta REST /api/bancos/{b_id}/cuentas."""
        return read_accounts_direct(offset, limit)

    @bank_app.post(f"/api/bancos/{b_id}/confirmar", tags=[f"Banco {b_id} - Ruta REST"])
    def confirm_account_by_bank_path(request: ConfirmationRequest) -> dict[str, Any]:
        """Confirma transacción en la ruta REST /api/bancos/{b_id}/confirmar."""
        return confirm_account_direct(request)

    @bank_app.get("/")
    def read_root() -> dict[str, object]:
        return {
            "service": "bank-service",
            "bank_id": b_id,
            "bank_name": b_meta["name"],
            "algorithm": b_meta["algorithm"],
            "storage": st,
            "data_file": str(df),
        }

    @bank_app.get("/health")
    def health() -> dict[str, object]:
        db_health = store.health_check() if hasattr(store, "health_check") else {}
        total = store.count_accounts() if hasattr(store, "count_accounts") else 0
        return {
            "status": "ok",
            "bank_id": b_id,
            "bank_name": b_meta["name"],
            "algorithm": b_meta["algorithm"],
            "storage": st,
            "data_file_exists": df.exists(),
            "total_cuentas": total,
            "db_health": db_health,
        }

    return bank_app


app = create_app()


