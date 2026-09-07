"""Carga un JSONL cifrado en Neo4j como Cliente, Cuenta y TIENE_CUENTA."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from common.neo4j_store import Neo4jStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    store = Neo4jStore(args.database_url)
    count = 0
    try:
        with args.source.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    store.upsert_account(json.loads(line))
                    count += 1
    finally:
        store.close()
    print(f"Registros cargados en Neo4j: {count}")


if __name__ == "__main__":
    main()
