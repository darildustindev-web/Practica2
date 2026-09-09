"""Carga incremental en neo4j."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'banks-services'))
from common.neo4j_store import Neo4jStore
try:
    from scripts.load_common import cli
except ModuleNotFoundError:
    from load_common import cli
if __name__ == '__main__':
    cli(Neo4jStore)
