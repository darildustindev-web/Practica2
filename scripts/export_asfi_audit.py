"""Reconstruye el log de consolidación desde la base durable, por lotes."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'asfi-service'))
from journal import Journal

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',default=os.getenv('ASFI_DATABASE_URL','sqlite:///'+str(ROOT/'data/asfi.sqlite')))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    journal=Journal(args.database_url)
    try:
        # Cursor del servidor para no materializar millones de filas PostgreSQL.
        cur=journal.db.cursor(name='audit_export') if journal.postgres else journal.db.cursor()
        cur.execute('SELECT payload,estado FROM asfi_cuentas ORDER BY banco_id,cuenta_id')
        with args.output.open('x',encoding='utf-8') as file:
            while True:
                rows=cur.fetchmany(1000)
                if not rows:break
                for payload,status in rows:
                    record=json.loads(payload);record.pop('datos',None);record['estado']=status
                    file.write(json.dumps(record,ensure_ascii=False)+'\n')
        cur.close()
    finally:journal.close()
