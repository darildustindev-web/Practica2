"""Consolidación durable y outbox: guardar antes de confirmar al banco."""
import json
import threading
from pathlib import Path


class Journal:
    def __init__(self, url):
        self.lock=threading.RLock()
        self.postgres=url.startswith(('postgresql://','postgres://'))
        if self.postgres:
            import psycopg2
            self.db=psycopg2.connect(url,connect_timeout=10)
            self.mark='%s'
        else:
            if not url.startswith('sqlite:///'):
                raise ValueError('ASFI_DATABASE_URL debe ser postgresql:// o sqlite:///')
            import sqlite3
            path=Path(url[10:]);path.parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(path,check_same_thread=False)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.mark='?'
        with self.db:
            cur=self.db.cursor()
            money_type='DECIMAL(18,4)' if self.postgres else 'TEXT'
            cur.execute(f'''CREATE TABLE IF NOT EXISTS asfi_cuentas (
                banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL,
                saldo_usd {money_type} NOT NULL, saldo_bs {money_type} NOT NULL,
                tipo_cambio {money_type} NOT NULL, codigo_verificacion CHAR(8) NOT NULL,
                fecha_conversion TEXT NOT NULL, estado TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY (banco_id,cuenta_id))''')
            cur.execute('CREATE TABLE IF NOT EXISTS asfi_historial (banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL, codigo_verificacion CHAR(8) NOT NULL, payload TEXT NOT NULL)')
            cur.close()

    def acquire(self):
        # Exclusión entre procesos ASFI que comparten PostgreSQL.
        if self.postgres:
            with self.lock:
                cur=self.db.cursor();cur.execute('SELECT pg_try_advisory_lock(20260909)')
                ok=cur.fetchone()[0];cur.close();self.db.commit()
                if not ok:
                    raise RuntimeError('Otro barrido ASFI está en ejecución')

    def lookup(self, bank, refs):
        if not refs:
            return {}
        with self.lock:
            cur=self.db.cursor()
            cur.execute('SELECT cuenta_id,payload,estado FROM asfi_cuentas WHERE banco_id='+self.mark+
                        ' AND cuenta_id IN ('+','.join([self.mark]*len(refs))+')',[bank,*refs])
            result={ref:dict(json.loads(payload),estado=status) for ref,payload,status in cur.fetchall()}
            cur.close()
            self.db.commit()
            return result

    def prepare(self, records, new_round=False):
        if not records:
            return []
        output=[]
        with self.lock, self.db:
            cur=self.db.cursor()
            bank=records[0]['banco_id']
            if any(r['banco_id']!=bank for r in records):
                raise ValueError('Un lote debe corresponder a un solo banco')
            refs=list(dict.fromkeys(r['cuenta_id'] for r in records))
            cur.execute('SELECT cuenta_id,payload,estado FROM asfi_cuentas WHERE banco_id='+self.mark+
                        ' AND cuenta_id IN ('+','.join([self.mark]*len(refs))+')',[bank,*refs])
            existing={row[0]:(row[1],row[2]) for row in cur.fetchall()}
            inserts=[]
            for record in records:
                ref=record['cuenta_id']
                previous=existing.get(ref)
                if previous and new_round and previous[1]=='CONFIRMADA':
                    old=json.loads(previous[0])
                    cur.execute('INSERT INTO asfi_historial VALUES ('+','.join([self.mark]*4)+')',
                                [bank,ref,old['codigo_verificacion'],previous[0]])
                    cur.execute('DELETE FROM asfi_cuentas WHERE banco_id='+self.mark+' AND cuenta_id='+self.mark,[bank,ref])
                    previous=None
                if previous:
                    saved=json.loads(previous[0]);saved['estado']=previous[1]
                    if saved['saldo_usd']!=record['saldo_usd']:
                        output.append(dict(record,estado='ERROR',detail='Saldo USD difiere del consolidado; requiere conciliación'))
                    else:
                        output.append(saved)
                    continue
                record=dict(record,estado='PENDIENTE')
                payload=json.dumps(record,ensure_ascii=False)
                inserts.append((bank,ref,record['saldo_usd'],record['saldo_bs'],record['tipo_cambio'],record['codigo_verificacion'],
                                record['timestamp'],'PENDIENTE',payload))
                existing[ref]=(payload,'PENDIENTE')
                output.append(record)
            if inserts:
                if self.postgres:
                    from psycopg2.extras import execute_values
                    execute_values(cur,'INSERT INTO asfi_cuentas VALUES %s',inserts,page_size=1000)
                else:
                    cur.executemany('INSERT INTO asfi_cuentas VALUES ('+','.join([self.mark]*9)+')',inserts)
            cur.close()
        return output

    def finish(self, records):
        with self.lock,self.db:
            cur=self.db.cursor()
            execute = cur.executemany
            if self.postgres:
                from psycopg2.extras import execute_batch
                execute = lambda sql, rows: execute_batch(cur, sql, rows, page_size=1000)
            execute('UPDATE asfi_cuentas SET estado='+self.mark+',payload='+self.mark+' WHERE banco_id='+self.mark+' AND cuenta_id='+self.mark,
                            [(r['estado'],json.dumps(r,ensure_ascii=False),r['banco_id'],r['cuenta_id']) for r in records])
            cur.close()

    def close(self):
        with self.lock:
            self.db.close()
