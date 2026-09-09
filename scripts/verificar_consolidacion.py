"""Compara todas las cuentas del dataset contra banco y ASFI, sin escribir en las bases.
Ejecutar con barridos y cargas detenidos para comparar una versión estable.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit, unquote
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'banks-services')]
from scripts.load_all import DEFAULTS
from shared.money import parse_money,convert_money


def bank_rows(bank):
    cls,default=DEFAULTS[bank];url=os.getenv(f'BANK_{bank:02d}_DATABASE_URL',default);kind=cls.__name__
    p=urlsplit(url)
    if kind in ('PostgreSQLStore','MySQLStore','SQLiteStore'):
        if kind=='PostgreSQLStore':
            import psycopg2
            db=psycopg2.connect(url,connect_timeout=10);db.set_session(readonly=True)
        elif kind=='MySQLStore':
            import pymysql
            db=pymysql.connect(host=p.hostname,port=p.port or 3306,user=unquote(p.username),password=unquote(p.password),database=p.path[1:],connect_timeout=10)
            with db.cursor() as cur:cur.execute('SET TRANSACTION READ ONLY')
        else:db=sqlite3.connect(Path(url[10:]).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            cur=db.cursor();cur.execute('SELECT nro,saldo_bs,tipo_cambio,codigo_verificacion FROM cuentas')
            while rows:=cur.fetchmany(1000):
                for row in rows:yield dict(zip(('ref','saldo_bs','tipo_cambio','codigo_verificacion'),row))
        finally:db.close()
    elif kind=='MongoStore':
        from pymongo import MongoClient
        with MongoClient(url,serverSelectionTimeoutMS=10000) as client:
            for row in client[p.path[1:]].cuentas.find({}, {'nro':1,'saldo_bs':1,'tipo_cambio':1,'codigo_verificacion':1}).batch_size(1000):
                yield dict(row,ref=row['nro'])
    elif kind=='RedisStore':
        from redis import Redis
        prefix='bank:'+p.fragment.removeprefix('bank')
        with Redis.from_url(url.split('#')[0],decode_responses=True,socket_timeout=10) as client:
            offset=0
            while refs:=client.zrange(prefix+':index',offset,offset+999):
                with client.pipeline(transaction=False) as pipe:
                    for ref in refs:pipe.hgetall(prefix+':cuenta:'+ref)
                    for ref,row in zip(refs,pipe.execute()):yield dict(row,ref=ref)
                offset+=len(refs)
    else:
        from neo4j import GraphDatabase,READ_ACCESS
        with GraphDatabase.driver(f'neo4j://{p.hostname}:{p.port or 7687}',auth=(unquote(p.username),unquote(p.password))) as driver:
            with driver.session(default_access_mode=READ_ACCESS) as session:
                for row in session.run('MATCH (c:Cuenta) RETURN c.cuentaId AS ref,c.saldo_bs AS saldo_bs,c.tipo_cambio AS tipo_cambio,c.codigo_verificacion AS codigo_verificacion'):
                    yield dict(row)


def verify(source,asfi_url):
    if asfi_url.startswith(('postgresql://','postgres://')):
        import psycopg2
        db=psycopg2.connect(asfi_url,connect_timeout=10);db.set_session(readonly=True);mark='%s'
    else:
        db=sqlite3.connect(Path(asfi_url[10:]).resolve().as_uri()+'?mode=ro',uri=True);mark='?'
    results=[];started=perf_counter()
    try:
        for bank in range(1,15):
            with (source/f'bank_{bank:02d}.jsonl').open() as f:expected={str(json.loads(line)['Nro']) for line in f if line.strip()}
            cur=db.cursor();cur.execute('SELECT cuenta_id,saldo_usd,saldo_bs,tipo_cambio,codigo_verificacion,estado FROM asfi_cuentas WHERE banco_id='+mark,(bank,))
            central={str(row[0]):row[1:] for row in cur};cur.close()
            seen=set();errors=Counter();rates=set();digest=hashlib.sha256();compared=0
            for row in bank_rows(bank):
                ref=str(row['ref'])
                if ref in seen:errors['referencia_duplicada']+=1
                seen.add(ref)
                a=central.get(ref)
                if a is None:errors['ausente_asfi']+=1;continue
                try:
                    usd,bs,rate,code,status=a
                    if parse_money(bs)!=parse_money(row['saldo_bs']):errors['saldo']+=1
                    if parse_money(rate)!=parse_money(row['tipo_cambio']):errors['tasa']+=1
                    if code!=row['codigo_verificacion'] or not re.fullmatch('[0-9A-F]{8}',code or ''):errors['codigo']+=1
                    if convert_money(usd,rate)!=parse_money(bs):errors['calculo']+=1
                    if status!='CONFIRMADA':errors['estado']+=1
                    rates.add(str(rate));compared+=1
                except (ValueError,TypeError):errors['formato']+=1
            for ref in sorted(central):digest.update((ref+':'+str(central[ref][3])+'\n').encode())
            for name,n in [('faltantes_dataset',len(expected-seen)),('adicionales_banco',len(seen-expected)),('adicionales_asfi',len(set(central)-expected)),('faltantes_asfi',len(expected-set(central)))]:
                if n:errors[name]+=n
            result=dict(banco_id=bank,esperadas=len(expected),banco=len(seen),asfi=len(central),comparadas=compared,errores=dict(errors),tasas_distintas=len(rates),huella_codigos=digest.hexdigest())
            results.append(result);print(json.dumps(result),flush=True)
    finally:db.close()
    return dict(fecha_utc=datetime.now(timezone.utc).isoformat(),segundos=round(perf_counter()-started,3),coincide=all(not r['errores'] for r in results),total_comparadas=sum(r['comparadas'] for r in results),bancos=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-dir',type=Path,default=ROOT/'data/seed')
    p.add_argument('--asfi-url',default=os.getenv('ASFI_DATABASE_URL','sqlite:///'+str(ROOT/'data/asfi.sqlite')))
    p.add_argument('--output',type=Path)
    a=p.parse_args();result=verify(a.source_dir,a.asfi_url)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('COINCIDE' if result['coincide'] else 'DIFERENCIAS',result['total_comparadas'],'cuentas',result['segundos'],'s')
    sys.exit(0 if result['coincide'] else 1)
