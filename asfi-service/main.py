from __future__ import annotations
import asyncio
import json
import hashlib
import os
import secrets
import uuid
from contextvars import ContextVar
import sys
import fcntl
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared.money import parse_money, convert_money
from crypto.key_manager import CipherFactory
from journal import Journal
from monitor import monitor

app=FastAPI(title='Servicio Central ASFI',version='2.0.0')
BCB_URL=os.getenv('BCB_URL','http://localhost:8001/api/bcb/tipo-cambio')
AUDIT_FILE=Path(os.getenv('ASFI_AUDIT_FILE',str(ROOT/'data/audit.jsonl')))
DATABASE_URL=os.getenv('ASFI_DATABASE_URL','sqlite:///'+str(ROOT/'data/asfi.sqlite'))
_CIPHERS={}


def bank_urls():
    ids=[int(v.strip()) for v in os.getenv('ACTIVE_BANK_IDS',','.join(map(str,range(1,15)))).split(',') if v.strip()]
    if not ids or any(i not in range(1,15) for i in ids):
        raise ValueError('ACTIVE_BANK_IDS debe contener bancos 1..14')
    return {i:os.getenv(f'BANK_URL_{i}',f'http://localhost:{8100+i}/api/banco') for i in ids}


def generate_verification_code():
    return secrets.token_hex(4).upper()


async def request_retry(client, method, url, **kwargs):
    for attempt in range(3):
        try:
            response=await client.request(method,url,**kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (429,500,502,503,504):
                raise
            if attempt==2:
                raise
            await asyncio.sleep(0.2 * 2**attempt)


async def get_exchange_rate(client):
    response=await request_retry(client,'GET',BCB_URL)
    data=response.json()
    rate=parse_money(data.get('tipo_cambio_formateado',data.get('tipo_cambio')),rate=True)
    timestamp=datetime.fromisoformat(data['timestamp'])
    if timestamp.tzinfo is None:
        raise ValueError('BCB envió timestamp sin zona horaria')
    age=(datetime.now(timezone.utc)-timestamp).total_seconds()
    interval=int(data['intervalo_actual_segundos'])
    if interval<1 or age < -5 or age>interval+5:
        raise ValueError('Cotización BCB vencida o timestamp inválido')
    if not parse_money('5.9601')<=rate<=parse_money('7.9599'):
        raise ValueError('Cotización BCB fuera del rango del enunciado')
    return rate,timestamp.isoformat()


def account_fingerprint(account):
    fields=('Nro','IdBanco','Identificacion','Nombres','Apellidos','NroCuenta','Saldo')
    return hashlib.sha256(json.dumps({f:account.get(f) for f in fields},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def decrypt_batch(bank, accounts):
    if bank not in _CIPHERS:
        _CIPHERS[bank]=CipherFactory.get_cipher_for_bank(bank)
    cipher,key=_CIPHERS[bank]
    output=[]
    for index,account in enumerate(accounts):
        ref=str(account.get('Nro','')) if isinstance(account,dict) else ''
        try:
            if not isinstance(account,dict) or not ref.isascii() or not ref.isdigit():
                raise ValueError('Referencia de cuenta inválida')
            if int(account['IdBanco'])!=bank:
                raise ValueError('La cuenta pertenece a otro banco')
            decoded={field:cipher.decrypt(account[field],key) for field in ('Identificacion','Nombres','Apellidos','NroCuenta','Saldo')}
            decoded['Saldo']=format(parse_money(decoded['Saldo']),'f')
            record=dict(banco_id=bank,cuenta_id=ref,saldo_usd=decoded['Saldo'],datos=decoded,origen_hash=account_fingerprint(account))
            if bank==9:
                record['cifrado_origen']='TWOFISH_TF1' if all(str(account[f]).startswith('TF1:') for f in decoded) else 'LEGACY_AES_O_MIXTO'
            output.append(record)
        except Exception as exc:
            output.append(dict(banco_id=bank,cuenta_id=ref,estado='ERROR',detail=f'Descifrado: {type(exc).__name__}: {exc}'))
    return output


AUDIT_RUN = ContextVar('audit_run', default=None)


def append_audit(records):
    AUDIT_FILE.parent.mkdir(parents=True,exist_ok=True)
    with AUDIT_FILE.open('a',encoding='utf-8') as file:
        fcntl.flock(file,fcntl.LOCK_EX)
        for record in records:
            # Datos personales completos sólo en la consolidación, no en el log.
            item={k:v for k,v in record.items() if k!='datos'}
            item.update(audit_timestamp=datetime.now(timezone.utc).isoformat(), barrido_id=AUDIT_RUN.get() or 'fuera-de-barrido')
            item.setdefault('evento', 'CUENTA' if item.get('cuenta_id') else 'BANCO')
            file.write(json.dumps(item,ensure_ascii=False)+'\n')
        file.flush();os.fsync(file.fileno())


async def process_bank(client,bank,base_url,journal,pool,batch_size,crypto_chunks=1,new_round=False):
    start=perf_counter()
    stats=dict(banco_id=bank,leidas=0,confirmadas=0,ya_confirmadas=0,errores=0,lotes=0)
    monitor.bank(stats, 'Consultando')
    offset=0
    previous_page=None
    cursor=None
    try:
        while True:
            page_start=perf_counter()
            response=await request_retry(client,'GET',f'{base_url}/cuentas/cifradas',params=dict(after=cursor,limit=batch_size) if cursor is not None else dict(offset=offset,limit=batch_size))
            page=response.json()
            accounts=page['cuentas']
            response_cursor=page.get('next_cursor')
            if not isinstance(accounts,list) or len(accounts)>batch_size:
                raise ValueError('Respuesta de página inválida')
            if not accounts:
                break
            stats['leidas']+=len(accounts)
            page_refs=[str(r.get('Nro','')) for r in accounts if isinstance(r,dict)]
            signature=tuple(page_refs)
            if signature and signature==previous_page:
                raise ValueError('El banco repitió una página; paginación detenida')
            previous_page=signature
            saved=await asyncio.to_thread(journal.lookup,bank,page_refs)
            fresh=[];resuming=[];source_errors=[]
            seen_refs=set()
            for account in accounts:
                ref=str(account.get('Nro','')) if isinstance(account,dict) else ''
                if ref and ref in seen_refs:
                    source_errors.append(dict(banco_id=bank,cuenta_id=ref,estado='ERROR',detail='Referencia duplicada en la página'))
                    continue
                seen_refs.add(ref)
                prior=saved.get(ref)
                if prior:
                    if prior.get('origen_hash') != account_fingerprint(account):
                        # Un recifrado puede cambiar los bytes sin cambiar los datos.
                        fresh.append(account)
                    elif prior['estado']=='CONFIRMADA':
                        if new_round:
                            fresh.append(account)
                        else:
                            stats['ya_confirmadas']+=1
                    else:
                        resuming.append(prior)
                else:
                    fresh.append(account)
            loop=asyncio.get_running_loop()
            if fresh:
                monitor.bank(stats, 'Descifrando')
                if pool:
                    chunk_size=max(1,(len(fresh)+crypto_chunks-1)//crypto_chunks)
                    chunks=await asyncio.gather(*(loop.run_in_executor(pool,decrypt_batch,bank,fresh[i:i+chunk_size])
                                                  for i in range(0,len(fresh),chunk_size)))
                    parsed=[record for chunk in chunks for record in chunk]
                else:
                    parsed=await asyncio.to_thread(decrypt_batch,bank,fresh)
                checked=[]; reconciled=[]
                for record in parsed:
                    prior=saved.get(record['cuenta_id'])
                    if prior and record.get('estado')!='ERROR':
                        if prior.get('datos')!=record['datos'] or prior.get('saldo_usd')!=record['saldo_usd']:
                            source_errors.append(dict(banco_id=bank,cuenta_id=record['cuenta_id'],estado='ERROR',
                                                      detail='Datos descifrados distintos del consolidado; requiere conciliación'))
                            continue
                        if prior['estado']!='CONFIRMADA' or not new_round:
                            prior=dict(prior,origen_hash=record['origen_hash'])
                            if prior['estado']=='CONFIRMADA':
                                stats['ya_confirmadas']+=1
                                reconciled.append(prior)
                            else:
                                resuming.append(prior)
                            continue
                    checked.append(record)
                parsed=checked
                if reconciled:
                    await asyncio.to_thread(journal.finish,reconciled)
                if any(r.get('estado')!='ERROR' for r in parsed):
                    rate,rate_timestamp=await get_exchange_rate(client)
            else:
                parsed=[]
            converted_at=datetime.now(timezone.utc).isoformat()
            valid=[];errors=source_errors
            for record in parsed:
                if record.get('estado')=='ERROR':
                    errors.append(record);continue
                try:
                    record.update(saldo_bs=format(convert_money(record['saldo_usd'],rate),'f'),tipo_cambio=format(rate,'f'),
                                  bcb_timestamp=rate_timestamp,timestamp=converted_at,codigo_verificacion=generate_verification_code())
                    valid.append(record)
                except ValueError as exc:
                    errors.append(dict(record,estado='ERROR',detail=str(exc)))
            monitor.bank(stats, 'Consolidando')
            prepared=await asyncio.to_thread(journal.prepare,valid,new_round)
            pending=resuming
            for record in prepared:
                if record['estado']=='CONFIRMADA':
                    stats['ya_confirmadas']+=1
                elif record['estado']=='ERROR':
                    errors.append(record)
                else:
                    pending.append(record)
            if pending:
                monitor.bank(stats, 'Confirmando')
                payload=[dict(account_ref=r['cuenta_id'],verification_code=r['codigo_verificacion'],saldo_bs=r['saldo_bs'],
                              exchange_rate=r['tipo_cambio'],converted_at=r['timestamp'],revalue=True) for r in pending]
                try:
                    response=await request_retry(client,'POST',f'{base_url}/cuentas/confirmar',json=payload)
                    receipts=response.json()['resultados']
                    if not isinstance(receipts,list):
                        raise ValueError('Recibos inválidos')
                    by_ref={}
                    for receipt in receipts:
                        ref=str(receipt['account_ref'])
                        if ref in by_ref:
                            raise ValueError('Recibo duplicado')
                        by_ref[ref]=receipt
                    for record in pending:
                        receipt=by_ref.get(record['cuenta_id'],{})
                        try:
                            if (receipt.get('status')!='CONFIRMADA' or receipt.get('verification_code')!=record['codigo_verificacion']
                                or parse_money(receipt.get('saldo_bs'))!=parse_money(record['saldo_bs'])
                                or parse_money(receipt.get('exchange_rate'))!=parse_money(record['tipo_cambio'])):
                                raise ValueError(receipt.get('detail') or 'Banco no confirmó código, saldo y tasa esperados')
                            record['estado']='CONFIRMADA'
                            record.pop('detail',None)
                            stats['confirmadas']+=1
                        except ValueError as exc:
                            record.update(estado='PENDIENTE',detail=str(exc))
                            stats['errores']+=1
                except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
                    for record in pending:
                        record.update(estado='PENDIENTE',detail=f'Confirmación recuperable: {type(exc).__name__}',
                                      error_tipo=type(exc).__name__, http_status=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None,
                                      etapa='confirmacion', reintentable=True)
                    stats['errores']+=len(pending)
                await asyncio.to_thread(journal.finish,pending)
            stats['errores']+=len(errors)
            await asyncio.to_thread(append_audit,pending+errors)
            stats['lotes']+=1
            stats['ultimo_lote_segundos']=round(perf_counter()-page_start,4)
            stats['segundos']=round(perf_counter()-start,4)
            monitor.bank(stats, 'Procesando', pending+errors)
            offset+=len(accounts)
            cursor=response_cursor
            if len(accounts)<batch_size:
                break
    except Exception as exc:
        stats['errores']+=1
        stats['error_banco']=f'{type(exc).__name__}: {exc}'
        await asyncio.to_thread(append_audit,[dict(banco_id=bank,estado='ERROR_BANCO',detail=stats['error_banco'],offset=offset)])
    stats['segundos']=round(perf_counter()-start,4)
    stats['registros_por_segundo']=round(stats['leidas']/max(stats['segundos'],0.0001),2)
    monitor.bank(stats, 'Con errores' if stats['errores'] else 'Completado')
    return stats


async def _execute_conversion(client=None,new_round=False):
    start=perf_counter()
    batch_size=int(os.getenv('ASFI_BATCH_SIZE','500'))
    workers=int(os.getenv('ASFI_CRYPTO_WORKERS','2'))
    if not 1<=batch_size<=1000 or not 0<=workers<=32:
        raise ValueError('ASFI_BATCH_SIZE: 1..1000; ASFI_CRYPTO_WORKERS: 0..32')
    urls=bank_urls()
    lockpath=Path(DATABASE_URL[10:]+'.lock') if DATABASE_URL.startswith('sqlite:///') else ROOT/'data/asfi-conversion.lock'
    lockpath.parent.mkdir(parents=True,exist_ok=True)
    with lockpath.open('a') as lockfile:
        try:
            fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Ya hay un barrido ASFI en ejecución') from exc
        journal=await asyncio.to_thread(Journal,DATABASE_URL)
        pool=None;owned=client is None
        try:
            await asyncio.to_thread(journal.acquire)
            if workers:
                # Las claves persistentes deben existir antes del fork.
                for bank in (11,13):
                    await asyncio.to_thread(CipherFactory.get_cipher_for_bank,bank)
                import multiprocessing
                pool=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'))
            if owned:
                client=httpx.AsyncClient(timeout=httpx.Timeout(120,connect=10),limits=httpx.Limits(max_connections=32))
            results=await asyncio.gather(*(process_bank(client,b,url,journal,pool,batch_size,min(max(workers,1),4),new_round) for b,url in urls.items()))
            elapsed=perf_counter()-start
            errors=sum(r['errores'] for r in results)
            return dict(status='PARCIAL' if errors else 'PROCESADO',transacciones=sum(r['leidas'] for r in results),
                        confirmadas=sum(r['confirmadas'] for r in results),ya_confirmadas=sum(r['ya_confirmadas'] for r in results),
                        errores=errors,segundos=round(elapsed,4),bancos=results)
        finally:
            if owned and client:
                await client.aclose()
            if pool:
                await asyncio.to_thread(pool.shutdown,wait=True,cancel_futures=True)
            await asyncio.to_thread(journal.close)


async def execute_conversion(client=None,new_round=False):
    monitor.begin()
    run_id=uuid.uuid4().hex
    monitor.run_id=run_id
    token=AUDIT_RUN.set(run_id)
    try:
        await asyncio.to_thread(append_audit,[dict(evento='INICIO_BARRIDO',nuevo_barrido=new_round)])
        result = await _execute_conversion(client,new_round)
        result['barrido_id']=run_id
        await asyncio.to_thread(append_audit,[dict(evento='FIN_BARRIDO',**result)])
        monitor.end(result=result)
        return result
    except BaseException as exc:
        await asyncio.to_thread(append_audit,[dict(evento='FALLO_BARRIDO',error_tipo=type(exc).__name__,detail=str(exc))])
        monitor.end(error=exc)
        raise
    finally:
        AUDIT_RUN.reset(token)


@app.get('/')
def read_root():
    return {'message':'Servicio Central ASFI Operativo'}


@app.post('/api/asfi/ejecutar-conversion')
async def ejecutar_barrido_conversion():
    try:
        return await execute_conversion(new_round=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409,detail=str(exc)) from exc
    except (ValueError,httpx.HTTPError) as exc:
        raise HTTPException(status_code=502,detail=str(exc)) from exc


from dashboard import install_dashboard
async def execute_new_round():
    return await execute_conversion(new_round=True)

install_dashboard(app, execute_new_round, lambda: BCB_URL, lambda: DATABASE_URL, bank_urls)
