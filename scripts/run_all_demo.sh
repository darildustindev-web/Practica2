#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
UV="$ROOT/.venv/bin/uvicorn"
DATA="$ROOT/data/seed"
SQLITE_DB="$ROOT/data/bank_03.sqlite"

[[ -f "$DATA/bank_14.jsonl" ]] || {
  echo "Faltan archivos en $DATA. Ejecuta el seeder antes." >&2
  exit 1
}

load() {
  "$PY" "$ROOT/scripts/$1" "$DATA/bank_$(printf '%02d' "$2").jsonl" \
    --database-url "$3"
}

"$PY" "$ROOT/scripts/load_all.py" --source-dir "$DATA" --workers 4

pids=()
cleanup() {
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

start() {
  "$@" &
  pids+=("$!")
}

start env "$PY" -m uvicorn main:app --app-dir "$ROOT/bcb-service" \
  --host 127.0.0.1 --port 8001

start_bank() {
  local bank_id="$1" storage="$2" url="$3" port="$4"
  start env BANK_ID="$bank_id" BANK_STORAGE="$storage" DATABASE_URL="$url" \
    "$UV" bank_template.main:app --app-dir "$ROOT/banks-services" \
    --host 127.0.0.1 --port "$port"
}

start_bank 1 postgres "postgresql://union_user:union_password@127.0.0.1:5433/bank_union" 8101
start_bank 2 mysql "mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil" 8102
start_bank 3 sqlite "sqlite:///$SQLITE_DB" 8103
start_bank 4 postgres "postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp" 8104
start_bank 5 mysql "mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa" 8105
start_bank 6 postgres "postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero" 8106
start_bank 7 mysql "mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico" 8107
start_bank 8 mongo "mongodb://127.0.0.1:27017/bank_prodem" 8108
start_bank 9 mongo "mongodb://127.0.0.1:27017/bank_solidario" 8109
start_bank 10 redis "redis://127.0.0.1:6379/0#bank10" 8110
start_bank 11 mongo "mongodb://127.0.0.1:27017/bank_fie" 8111
start_bank 12 mongo "mongodb://127.0.0.1:27017/bank_pyme" 8112
start_bank 13 neo4j "neo4j://neo4j:bdp_password@127.0.0.1:7687" 8113
start_bank 14 mongo "mongodb://127.0.0.1:27017/bank_argentina" 8114

bank_ids=$(seq -s, 1 14)
start env ACTIVE_BANK_IDS="$bank_ids" \
  ASFI_DATABASE_URL="${ASFI_DATABASE_URL:-postgresql://asfi_user:asfi_password@127.0.0.1:5434/asfi_db}" \
  BCB_URL=http://127.0.0.1:8001/api/bcb/tipo-cambio \
  "$UV" main:app --app-dir "$ROOT/asfi-service" \
  --host 127.0.0.1 --port 8000

for port in $(seq 8101 8114); do
  for attempt in $(seq 1 20); do
    curl --fail --silent "http://127.0.0.1:$port/health" >/dev/null && break
    [[ "$attempt" == 20 ]] && {
      echo "El servicio en el puerto $port no respondió." >&2
      exit 1
    }
    sleep 0.5
  done
done

for endpoint in \
  "http://127.0.0.1:8001/api/bcb/tipo-cambio" \
  "http://127.0.0.1:8000/"; do
  for attempt in $(seq 1 20); do
    curl --fail --silent "$endpoint" >/dev/null && break
    [[ "$attempt" == 20 ]] && {
      echo "El servicio $endpoint no respondió." >&2
      exit 1
    }
    sleep 0.5
  done
done

curl --fail --silent --show-error --max-time 300 -X POST \
  http://127.0.0.1:8000/api/asfi/ejecutar-conversion
printf '\nBarrido de 14 bancos completado. Presiona Ctrl+C para detener servicios.\n'
wait
