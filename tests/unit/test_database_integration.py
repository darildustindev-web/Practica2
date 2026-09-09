"""RUN_DB_TESTS=1: motores reales con esquemas/namespaces propios y limpieza acotada."""
import os
import sys
import uuid
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'banks-services'),str(ROOT/'asfi-service'),str(Path(__file__).parent)]
from test_pipeline import encrypted,confirmation
from common.bank_router import ConfirmationRequest

@unittest.skipUnless(os.getenv('RUN_DB_TESTS')=='1','Requiere motores Docker; habilitar explícitamente')
class DatabaseIntegration(unittest.TestCase):
    def recotizacion(self,store,original):
        from datetime import timedelta
        new=original.model_copy(update={'verification_code':'ABCD9876','saldo_bs':'900.0000',
            'exchange_rate':'7.2900','converted_at':original.converted_at+timedelta(seconds=1),'revalue':True})
        self.assertEqual(store.confirm_batch([new])[0]['status'],'CONFIRMADA')
        self.assertEqual(store.confirm_batch([new])[0]['status'],'CONFIRMADA')
        stale=original.model_copy(update={'revalue':True})
        self.assertEqual(store.confirm_batch([stale])[0]['status'],'ERROR')
        tampered=new.model_copy(update={'saldo_bs':'1.0000'})
        self.assertEqual(store.confirm_batch([tampered])[0]['status'],'ERROR')
        self.assertEqual(store.confirm_batch([new])[0]['saldo_bs'],'900.0000')

    def exercise(self,store):
        rows=[encrypted(i,3) for i in range(1,1001)]
        store.upsert_accounts_batch(rows)
        self.assertEqual(len(store.encrypted_accounts(0,1000)),1000)
        seen=[];cursor=''
        while True:
            page=store.encrypted_accounts_after(cursor,137)
            if not page:break
            seen.extend(r['Nro'] for r in page)
            cursor=page[-1]['Nro']
        self.assertEqual(len(seen),1000)
        self.assertEqual(len(set(seen)),1000)
        requests=[ConfirmationRequest(**confirmation(i)) for i in range(1,1001)]
        receipts=store.confirm_batch(requests)
        self.assertEqual(sum(r['status']=='CONFIRMADA' for r in receipts),1000)
        self.assertTrue(all(r['status']=='CONFIRMADA' for r in store.confirm_batch(requests)))
        store.upsert_accounts_batch(rows)
        bad=ConfirmationRequest(**confirmation(1,amount='1.0000'))
        self.assertEqual(store.confirm_batch([bad])[0]['status'],'ERROR')
        self.assertEqual(store.confirm_batch([requests[0]])[0]['status'],'CONFIRMADA')
        self.recotizacion(store,requests[0])

    def test_postgres_and_journal(self):
        import psycopg2
        from common.postgresql_store import PostgreSQLStore
        from journal import Journal
        name='asfi_test_'+uuid.uuid4().hex
        url='postgresql://union_user:union_password@127.0.0.1:5433/bank_union'
        admin=psycopg2.connect(url);admin.autocommit=True
        with admin.cursor() as cur:cur.execute(f'CREATE SCHEMA {name}')
        store=None;journal=None
        try:
            target=url+'?options=-csearch_path%3D'+name
            store=PostgreSQLStore(target);self.exercise(store)
            journal=Journal(target);journal.acquire()
            record=dict(banco_id=3,cuenta_id='1',saldo_usd='10.0000',saldo_bs='69.6000',tipo_cambio='6.9600',
                        codigo_verificacion='1234ABCD',timestamp='2026-09-09T00:00:00+00:00')
            prepared=journal.prepare([record]);self.assertEqual(prepared[0]['estado'],'PENDIENTE')
            prepared[0]['estado']='CONFIRMADA';journal.finish(prepared)
            self.assertEqual(journal.lookup(3,['1'])['1']['estado'],'CONFIRMADA')
        finally:
            if journal:journal.close()
            if store:store._connection.close()
            with admin.cursor() as cur:cur.execute(f'DROP SCHEMA {name} CASCADE')
            admin.close()

    def test_mysql(self):
        import pymysql
        from common.mysql_store import MySQLStore
        name='asfi_test_'+uuid.uuid4().hex
        admin=pymysql.connect(host='127.0.0.1',port=3306,user='root',password='root_password',autocommit=True)
        with admin.cursor() as cur:cur.execute(f'CREATE DATABASE {name}')
        store=None
        try:
            store=MySQLStore(f'mysql://root:root_password@127.0.0.1:3306/{name}')
            reader=MySQLStore(f'mysql://root:root_password@127.0.0.1:3306/{name}')
            try:
                self.assertEqual(reader.count_accounts(),0)
                self.assertEqual(reader.encrypted_accounts(0,10),[])
                self.exercise(store)
                self.assertEqual(reader.count_accounts(),1000)
                self.assertEqual(len(reader.encrypted_accounts(0,10)),10)
                self.assertEqual(len(reader.encrypted_accounts_after('',10)),10)
                self.assertIsNotNone(reader.get_account('1'))
            finally:
                reader._connection.close()
        finally:
            if store:store._connection.close()
            with admin.cursor() as cur:cur.execute(f'DROP DATABASE {name}')
            admin.close()

    def test_mongo(self):
        from common.mongo_store import MongoStore
        name='asfi_test_'+uuid.uuid4().hex
        store=MongoStore('mongodb://127.0.0.1:27017/'+name,bank_id=3)
        try:self.exercise(store)
        finally:store._client.drop_database(name);store._client.close()

    def test_redis(self):
        from common.redis_store import RedisStore
        name='asfi_test_'+uuid.uuid4().hex
        store=RedisStore('redis://127.0.0.1:6379/0#'+name,bank_id=0)
        try:self.exercise(store)
        finally:
            keys=list(store._redis.scan_iter(match=store.prefix+':*'))
            if keys:store._redis.delete(*keys)
            store._redis.close()

    def test_neo4j(self):
        from common.neo4j_store import Neo4jStore
        store=Neo4jStore('neo4j://neo4j:bdp_password@127.0.0.1:7687')
        base=int(uuid.uuid4().hex[:12],16)
        refs=[str(base+i) for i in range(100)]
        rows=[encrypted(ref,13) for ref in refs]
        clients=[r['Identificacion'] for r in rows]
        try:
            store.upsert_accounts_batch(rows)
            requests=[ConfirmationRequest(**confirmation(ref)) for ref in refs]
            self.assertTrue(all(r['status']=='CONFIRMADA' for r in store.confirm_batch(requests)))
            self.assertTrue(all(r['status']=='CONFIRMADA' for r in store.confirm_batch(requests)))
            store.upsert_accounts_batch(rows)
            self.assertEqual(store.confirm_batch([ConfirmationRequest(**confirmation(refs[0],amount='1.0000'))])[0]['status'],'ERROR')
            self.recotizacion(store,requests[0])
        finally:
            with store._driver.session() as session:
                session.run('MATCH (cu:Cuenta) WHERE cu.cuentaId IN $refs DETACH DELETE cu',refs=refs).consume()
                session.run('MATCH (cl:Cliente) WHERE cl.clienteId IN $refs AND NOT (cl)--() DELETE cl',refs=clients).consume()
            store.close()
