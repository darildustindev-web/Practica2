"""Confirmaciones por lote con comprobación atómica en el servidor."""
from shared.money import parse_money


def receipt(request, row):
    try:
        if not row or row.get('codigo_verificacion')!=request.verification_code:
            raise ValueError('Cuenta inexistente o confirmada con otro código')
        if parse_money(row.get('saldo_bs'))!=parse_money(request.saldo_bs) or parse_money(row.get('tipo_cambio'))!=parse_money(request.exchange_rate):
            raise ValueError('Importe o tasa no coinciden con la confirmación persistida')
        return dict(account_ref=request.account_ref,status='CONFIRMADA',verification_code=request.verification_code,
                    saldo_bs=str(row['saldo_bs']),exchange_rate=str(row['tipo_cambio']),converted_at=str(row.get('convertido_at','')))
    except ValueError as exc:
        return dict(account_ref=request.account_ref,status='ERROR',detail=str(exc))


class NoSQLBulk:
    def confirm_batch(self, requests):
        if not requests:
            return []
        kind=self.__class__.__name__
        if kind=='MongoStore':
            from pymongo import UpdateOne
            operations=[]
            for r in requests:
                query={'nro':r.account_ref,'$or':[{'codigo_verificacion':None},{'codigo_verificacion':''}]}
                if r.revalue:
                    query['$or'].append({'codigo_verificacion': {'$ne': r.verification_code}, 'convertido_at': {'$lt': r.converted_at.isoformat()}})
                if self._bank_id>0:
                    query['id_banco']=self._bank_id
                operations.append(UpdateOne(query,{'$set':dict(codigo_verificacion=r.verification_code,saldo_bs=r.saldo_bs,
                                                               tipo_cambio=r.exchange_rate,convertido_at=r.converted_at.isoformat(),estado='CONFIRMADA')}))
            self._collection.bulk_write(operations,ordered=True)
            query={'nro':{'$in':[r.account_ref for r in requests]}}
            if self._bank_id>0:
                query['id_banco']=self._bank_id
            rows={r['nro']:r for r in self._collection.find(query)}
            return [receipt(r,rows.get(r.account_ref)) for r in requests]
        if kind=='RedisStore':
            script="""
            if redis.call('EXISTS',KEYS[1]) == 0 then return '{}' end
            local code=redis.call('HGET',KEYS[1],'codigo_verificacion')
            local previous=redis.call('HGET',KEYS[1],'convertido_at')
            if not code or code == '' or (ARGV[5] == '1' and code ~= ARGV[1] and previous and previous < ARGV[4]) then
                redis.call('HSET',KEYS[1],'codigo_verificacion',ARGV[1],
                    'saldo_bs',ARGV[2],'tipo_cambio',ARGV[3],'convertido_at',ARGV[4],'estado','CONFIRMADA')
                redis.call('HSET',KEYS[2],'verification_code',ARGV[1],
                    'saldo_bs',ARGV[2],'tipo_cambio',ARGV[3],'convertido_at',ARGV[4],'estado','CONFIRMADA')
            end
            local fields=redis.call('HGETALL',KEYS[1])
            local result={}
            for i=1,#fields,2 do result[fields[i]]=fields[i+1] end
            return cjson.encode(result)
            """
            import json
            with self._redis.pipeline(transaction=False) as pipe:
                for r in requests:
                    pipe.eval(script,2,self._key(r.account_ref),self._tx_key(r.account_ref),r.verification_code,
                              r.saldo_bs,r.exchange_rate,r.converted_at.isoformat(),int(r.revalue))
                rows=[json.loads(value) for value in pipe.execute()]
            return [receipt(r,row) for r,row in zip(requests,rows)]
        if kind=='Neo4jStore':
            query="""
            UNWIND $requests AS r
            MATCH (cu:Cuenta {cuentaId:r.ref})
            SET cu.confirm_lock = coalesce(cu.confirm_lock,0) + 1
            WITH cu,r
            FOREACH (_ IN CASE WHEN coalesce(cu.codigoVerificacion,cu.codigo_verificacion,'') = '' OR
                (r.revalue AND coalesce(cu.codigoVerificacion,cu.codigo_verificacion,'') <> r.code
                 AND coalesce(cu.convertido_at,cu.fechaConversion,'9999') < r.time) THEN [1] ELSE [] END |
                SET cu.codigoVerificacion=r.code,cu.codigo_verificacion=r.code,
                    cu.saldoBs=r.amount,cu.saldo_bs=r.amount,cu.tipoCambio=r.rate,cu.tipo_cambio=r.rate,
                    cu.fechaConversion=r.time,cu.convertido_at=r.time,cu.estado='CONFIRMADA')
            RETURN cu.cuentaId AS ref, cu.codigo_verificacion AS codigo_verificacion,
                   cu.saldo_bs AS saldo_bs,cu.tipo_cambio AS tipo_cambio,cu.convertido_at AS convertido_at
            """
            data=[dict(ref=r.account_ref,code=r.verification_code,amount=r.saldo_bs,rate=r.exchange_rate,time=r.converted_at.isoformat(),revalue=r.revalue) for r in requests]
            with self._driver.session() as session:
                rows=session.execute_write(lambda tx: tx.run(query,requests=data).data())
            by_ref={row['ref']:row for row in rows}
            return [receipt(r,by_ref.get(r.account_ref)) for r in requests]
        raise TypeError('Motor desconocido')

    def confirm(self, request):
        result=self.confirm_batch([request])[0]
        if result['status']!='CONFIRMADA':
            getter=getattr(self,'get_account',None) or self.get_account_by_id
            if getter(request.account_ref) is None:
                raise KeyError(result['detail'])
            raise ValueError(result['detail'])
        return result
