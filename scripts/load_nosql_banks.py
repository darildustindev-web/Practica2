"""Script unificado de carga para las bases de datos NoSQL (MongoDB y Redis) de los Bancos 8 al 14.

Uso:
    python scripts/load_nosql_banks.py
    python scripts/load_nosql_banks.py --reset
    python scripts/load_nosql_banks.py --mongo-url mongodb://127.0.0.1:27017 --redis-url redis://127.0.0.1:6379/0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from common.mongo_store import MongoStore
from common.redis_store import RedisStore

NOSQL_BANKS = {
    8: {"name": "Banco Prodem S.A.", "db": "bank_prodem", "algorithm": "Blowfish"},
    9: {"name": "Banco Solidario S.A.", "db": "bank_solidario", "algorithm": "Twofish"},
    10: {"name": "Banco Fortaleza S.A.", "db": "bank_fortaleza", "algorithm": "AES"},
    11: {"name": "Banco FIE S.A.", "db": "bank_fie", "algorithm": "RSA"},
    12: {"name": "Banco PYME de la Comunidad S.A.", "db": "bank_pyme", "algorithm": "ElGamal"},
    13: {"name": "Banco de Desarrollo Productivo S.A.M.", "db": "bank_bdp", "algorithm": "ECC"},
    14: {"name": "Banco de la Nación Argentina", "db": "bank_argentina", "algorithm": "ChaCha20"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Carga datos NoSQL (MongoDB y Redis) para los Bancos 8 al 14.")
    parser.add_argument(
        "--mongo-url",
        default="mongodb://127.0.0.1:27017",
        help="URL base de conexión a MongoDB (por defecto: mongodb://127.0.0.1:27017)",
    )
    parser.add_argument(
        "--redis-url",
        default="redis://127.0.0.1:6379/0",
        help="URL de conexión a Redis (por defecto: redis://127.0.0.1:6379/0)",
    )
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "seed",
        help="Directorio donde residen los archivos JSONL generados por el seeder",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Limpia las colecciones y namespaces antes de poblar",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("=" * 75)
    print("Iniciando carga de bases de datos NoSQL para Bancos 8 al 14")
    print(f"MongoDB URL: {args.mongo_url}")
    print(f"Redis URL:   {args.redis_url}")
    print(f"Seed Dir:    {args.seed_dir}")
    print("=" * 75)

    total_mongo_loaded = 0
    total_redis_loaded = 0

    for bank_id, info in NOSQL_BANKS.items():
        seed_file = args.seed_dir / f"bank_{bank_id:02d}.jsonl"
        if not seed_file.exists():
            print(f"[ALERTA] Archivo {seed_file} no encontrado. Ejecuta seeder.py primero.")
            continue

        db_url = f"{args.mongo_url.rstrip('/')}/{info['db']}"
        mongo_store = MongoStore(db_url, bank_id=bank_id, redis_url=args.redis_url)

        if args.reset:
            mongo_store._collection.delete_many({})

        # Cargar registros desde JSONL
        records = []
        with seed_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))

        for rec in records:
            mongo_store.upsert_account(rec)

        mongo_count = mongo_store.count_accounts()
        total_mongo_loaded += mongo_count

        # Para Banco 10: poblar también RedisStore como almacén primario en memoria
        redis_count = 0
        if bank_id == 10:
            redis_store_url = f"{args.redis_url.rstrip('/')}#bank10"
            redis_store = RedisStore(redis_store_url, bank_id=10)
            if args.reset:
                for k in redis_store._redis.scan_iter(match=f"{redis_store.prefix}:*"):
                    redis_store._redis.delete(k)
            for rec in records:
                redis_store.upsert_account(rec)
            redis_count = redis_store.count_accounts()
            total_redis_loaded += redis_count

        print(
            f"Banco {bank_id:2d} | {info['name']:38s} | {info['algorithm']:10s} | "
            f"MongoDB [{info['db']}]: {mongo_count:2d} cuentas"
            + (f" | Redis [bank:10]: {redis_count:2d} cuentas" if bank_id == 10 else " | Redis: sincronizado")
        )

    print("=" * 75)
    print(f"Carga completada con éxito. Cuentas en MongoDB: {total_mongo_loaded}, Cuentas en Redis Banco 10: {total_redis_loaded}")
    print("=" * 75)


if __name__ == "__main__":
    main()
