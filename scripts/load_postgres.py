"""Carga incremental en postgres."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'banks-services'))
from common.postgresql_store import PostgreSQLStore
try:
    from scripts.load_common import cli
except ModuleNotFoundError:
    from load_common import cli
if __name__ == '__main__':
    cli(PostgreSQLStore)
