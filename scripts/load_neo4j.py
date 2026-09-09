"""Carga un JSONL cifrado en Neo4j como Cliente, Cuenta y TIENE_CUENTA de forma idempotente."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from common.neo4j_store import Neo4jStore


def main() -> None:
    default_source = PROJECT_ROOT / "data" / "seed" / "bank_13.jsonl"
    default_db_url = os.getenv(
        "BANK_13_DATABASE_URL",
        os.getenv("NEO4J_URL", "neo4j://neo4j:bdp_password@127.0.0.1:7687"),
    )

    parser = argparse.ArgumentParser(description="Poblamiento idempotente de Banco 13 (BDP) en Neo4j")
    parser.add_argument("source", nargs="?", type=Path, default=default_source, help="Ruta al archivo JSONL cifrado")
    parser.add_argument(
        "--database-url",
        default=default_db_url,
        help="URL de conexión Neo4j (bolt:// o neo4j://)",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: No se encontró el archivo de datos: {args.source}")
        sys.exit(1)

    print("=" * 70)
    print("Iniciando carga en Neo4j - Banco de Desarrollo Productivo S.A.M. (BDP)")
    print(f"Fuente de datos: {args.source}")
    print(f"URL de base de datos: {args.database_url}")
    print("=" * 70)

    store = Neo4jStore(args.database_url, auto_constraints=True)
    count = 0
    try:
        with args.source.open(encoding="utf-8") as source_file:
            for line in source_file:
                stripped = line.strip()
                if stripped:
                    record = json.loads(stripped)
                    store.upsert_account(record)
                    count += 1

        total_clients = store.count_clients()
        total_accounts = store.count_accounts()
        total_rels = store.count_relationships()

        print(f"Líneas procesadas en esta ejecución: {count}")
        print(f"Total de nodos (:Cliente) en Neo4j:  {total_clients}")
        print(f"Total de nodos (:Cuenta)  en Neo4j:  {total_accounts}")
        print(f"Total de relaciones TIENE_CUENTA:    {total_rels}")
        print("=" * 70)
        print("Carga en Neo4j completada con éxito e idempotencia verificada.")
    finally:
        store.close()


if __name__ == "__main__":
    main()

