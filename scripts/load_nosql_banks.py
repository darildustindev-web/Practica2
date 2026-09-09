"""Entrada compatible para cargar bancos 8..14 con lotes e hilos."""
import argparse
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.load_all import main as load_all

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-dir',type=Path,default=ROOT/'data/seed')
    parser.add_argument('--mongo-url',default='mongodb://127.0.0.1:27017')
    parser.add_argument('--redis-url',default='redis://127.0.0.1:6379/0')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    for bank,name in [(8,'prodem'),(9,'solidario'),(11,'fie'),(12,'pyme'),(14,'argentina')]:
        os.environ[f'BANK_{bank:02d}_DATABASE_URL']=args.mongo_url.rstrip('/')+'/bank_'+name
    os.environ['BANK_10_DATABASE_URL']=args.redis_url.split('#')[0]+'#bank10'
    sys.argv=[sys.argv[0],'--source-dir',str(args.seed_dir),'--banks','8,9,10,11,12,13,14','--workers',str(args.workers)]
    load_all()
