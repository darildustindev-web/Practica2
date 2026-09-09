"""Carga un JSONL cifrado en Redis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "banks-services"))

from common.redis_store import RedisStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    store = RedisStore(args.database_url)
    count = 0
    batch = []
    with args.source.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                batch.append(json.loads(line))
                count += 1
                if len(batch) >= 1000:
                    store.upsert_accounts_batch(batch)
                    batch = []
        if batch:
            store.upsert_accounts_batch(batch)
    print(f"Registros cargados en Redis: {count}")


if __name__ == "__main__":
    main()
