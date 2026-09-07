#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
UVICORN="$ROOT/.venv/bin/uvicorn"
DATA_DIR="$ROOT/data/seed"
SQLITE_DB="$ROOT/data/bank_03.sqlite"

if [[ ! -f "$DATA_DIR/bank_01.jsonl" ]]; then
  echo "Faltan datos cifrados en $DATA_DIR. Ejecuta primero el seeder." >&2
  exit 1
fi

"$PY" "$ROOT/scripts/load_postgres.py" "$DATA_DIR/bank_01.jsonl" \
  --database-url "postgresql://union_user:union_password@127.0.0.1:5433/bank_union"
"$PY" "$ROOT/scripts/load_mysql.py" "$DATA_DIR/bank_02.jsonl" \
  --database-url "mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil"
"$PY" "$ROOT/scripts/load_sqlite.py" "$DATA_DIR/bank_03.jsonl" \
  --database-url "sqlite:///$SQLITE_DB"
"$PY" "$ROOT/scripts/load_postgres.py" "$DATA_DIR/bank_04.jsonl" \
  --database-url "postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp"
"$PY" "$ROOT/scripts/load_mongo.py" "$DATA_DIR/bank_08.jsonl" \
  --database-url "mongodb://127.0.0.1:27017/bank_prodem"

pids=()
cleanup() {
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

start_service() {
  "$@" &
  pids+=("$!")
}

start_service "$UVICORN" main:app --app-dir "$ROOT/bcb-service" \
  --host 127.0.0.1 --port 8001
start_service env BANK_ID=1 BANK_STORAGE=postgres \
  DATABASE_URL="postgresql://union_user:union_password@127.0.0.1:5433/bank_union" \
  "$UVICORN" bank_template.main:app --app-dir "$ROOT/banks-services" \
  --host 127.0.0.1 --port 8101
start_service env BANK_ID=2 BANK_STORAGE=mysql \
  DATABASE_URL="mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil" \
  "$UVICORN" bank_template.main:app --app-dir "$ROOT/banks-services" \
  --host 127.0.0.1 --port 8102
start_service env BANK_ID=3 BANK_STORAGE=sqlite \
  DATABASE_URL="sqlite:///$SQLITE_DB" \
  "$UVICORN" bank_template.main:app --app-dir "$ROOT/banks-services" \
  --host 127.0.0.1 --port 8103
start_service env BANK_ID=4 BANK_STORAGE=postgres \
  DATABASE_URL="postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp" \
  "$UVICORN" bank_template.main:app --app-dir "$ROOT/banks-services" \
  --host 127.0.0.1 --port 8104
start_service env BANK_ID=8 BANK_STORAGE=mongo \
  DATABASE_URL="mongodb://127.0.0.1:27017/bank_prodem" \
  "$UVICORN" bank_template.main:app --app-dir "$ROOT/banks-services" \
  --host 127.0.0.1 --port 8108
start_service env ACTIVE_BANK_IDS=1,2,3,4,8 \
  BCB_URL=http://127.0.0.1:8001/api/bcb/tipo-cambio \
  BANK_URL_1=http://127.0.0.1:8101/api/banco \
  BANK_URL_2=http://127.0.0.1:8102/api/banco \
  BANK_URL_3=http://127.0.0.1:8103/api/banco \
  BANK_URL_4=http://127.0.0.1:8104/api/banco \
  BANK_URL_8=http://127.0.0.1:8108/api/banco \
  "$UVICORN" main:app --app-dir "$ROOT/asfi-service" \
  --host 127.0.0.1 --port 8000

sleep 3
curl --fail --silent --show-error -X POST \
  http://127.0.0.1:8000/api/asfi/ejecutar-conversion
printf '\nServicios activos. Presiona Ctrl+C para detenerlos.\n'
wait
