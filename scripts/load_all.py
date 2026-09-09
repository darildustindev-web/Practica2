"""Carga los bancos en paralelo con un número acotado de hilos."""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'banks-services')]
from scripts.load_common import load
from common.postgresql_store import PostgreSQLStore
from common.mysql_store import MySQLStore
from common.sqlite_store import SQLiteStore
from common.mongo_store import MongoStore
from common.redis_store import RedisStore
from common.neo4j_store import Neo4jStore

DEFAULTS={
1:(PostgreSQLStore,'postgresql://union_user:union_password@127.0.0.1:5433/bank_union'),
2:(MySQLStore,'mysql://mercantil_user:mercantil_password@127.0.0.1:3306/bank_mercantil'),
3:(SQLiteStore,'sqlite:///'+str(ROOT/'data/bank_03.sqlite')),
4:(PostgreSQLStore,'postgresql://bcp_user:bcp_password@127.0.0.1:5435/bank_bcp'),
5:(MySQLStore,'mysql://bisa_user:bisa_password@127.0.0.1:3307/bank_bisa'),
6:(PostgreSQLStore,'postgresql://ganadero_user:ganadero_password@127.0.0.1:5436/bank_ganadero'),
7:(MySQLStore,'mysql://economico_user:economico_password@127.0.0.1:3308/bank_economico'),
10:(RedisStore,'redis://127.0.0.1:6379/0#bank10'),
13:(Neo4jStore,'neo4j://neo4j:bdp_password@127.0.0.1:7687')}
for bank,name in [(8,'prodem'),(9,'solidario'),(11,'fie'),(12,'pyme'),(14,'argentina')]:
    DEFAULTS[bank]=(MongoStore,f'mongodb://127.0.0.1:27017/bank_{name}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=ROOT/'data/seed')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--batch-size',type=int,default=1000)
    parser.add_argument('--banks',default=','.join(map(str,range(1,15))))
    args=parser.parse_args()
    if not 1<=args.workers<=14 or not 1<=args.batch_size<=1000:
        parser.error('workers: 1..14; batch-size: 1..1000')
    ids=list(dict.fromkeys(int(v) for v in args.banks.split(',')))
    if not ids or any(i not in DEFAULTS for i in ids):parser.error('Bancos: 1..14')
    def job(bank):
        cls,url=DEFAULTS[bank]
        url=os.getenv(f'BANK_{bank:02d}_DATABASE_URL',url)
        store=cls(url)
        try:
            return dict(banco_id=bank,**load(args.source_dir/f'bank_{bank:02d}.jsonl',store,args.batch_size,bank))
        finally:
            close=getattr(store,'close',None)
            if close:close()
            elif hasattr(store,'_connection'):store._connection.close()
            elif hasattr(store,'_client'):store._client.close()
            elif hasattr(store,'_redis'):store._redis.close()
    started=perf_counter();results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(job,bank):bank for bank in ids}
        for task in as_completed(tasks):
            try:result=task.result()
            except Exception as exc:result=dict(banco_id=tasks[task],error=f'{type(exc).__name__}: {exc}')
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
    summary=dict(segundos=round(perf_counter()-started,4),bancos=results)
    (args.source_dir/'load-metrics.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if any('error' in r for r in results):sys.exit(1)

if __name__=='__main__':main()
