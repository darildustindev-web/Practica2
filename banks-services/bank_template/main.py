"""Servicio bancario parametrizable para desarrollo local."""
import os
from pathlib import Path

from fastapi import FastAPI

from common.bank_router import JsonBankStore, create_bank_router
from common.postgresql_store import PostgreSQLStore
from common.mysql_store import MySQLStore
from common.sqlite_store import SQLiteStore
from common.mongo_store import MongoStore
from common.neo4j_store import Neo4jStore
from common.redis_store import RedisStore


bank_id = int(os.getenv("BANK_ID", "1"))
if not 1 <= bank_id <= 14:
    raise ValueError("BANK_ID debe estar entre 1 y 14")

project_root = Path(__file__).resolve().parents[2]
storage = os.getenv("BANK_STORAGE", "json").lower()
data_file = Path(
    os.getenv("BANK_DATA_FILE", str(project_root / "data" / "seed" / f"bank_{bank_id:02d}.jsonl"))
)
if storage == "json":
    store = JsonBankStore(data_file)
elif storage == "postgres":
    database_url = os.environ["DATABASE_URL"]
    store = PostgreSQLStore(database_url)
elif storage == "mysql":
    database_url = os.environ["DATABASE_URL"]
    store = MySQLStore(database_url)
elif storage == "sqlite":
    store = SQLiteStore(os.environ["DATABASE_URL"])
elif storage == "mongo":
    store = MongoStore(os.environ["DATABASE_URL"])
elif storage == "neo4j":
    store = Neo4jStore(os.environ["DATABASE_URL"])
elif storage == "redis":
    store = RedisStore(os.environ["DATABASE_URL"])
else:
    raise ValueError(f"BANK_STORAGE no soportado: {storage}")
app = FastAPI(title=f"Servicio Banco {bank_id}", version="1.0.0")
app.include_router(create_bank_router(store, bank_id))


@app.get("/")
def read_root() -> dict[str, object]:
    return {
        "service": "bank-service",
        "bank_id": bank_id,
        "storage": storage,
        "data_file": str(data_file),
    }


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "bank_id": bank_id, "data_file_exists": data_file.exists()}
