"""Operaciones por lote y confirmación atómica para motores SQL."""
from shared.money import parse_money
from shared.conversion import newer_conversion


class RelationalBulk:
    def migrate_legacy_schema(self, cursor):
        """Migración aditiva desde cuentas con datos de cliente embebidos."""
        dialect = self.__class__.__name__
        if dialect == 'SQLiteStore':
            cursor.execute('PRAGMA table_info(cuentas)')
            columns = {row[1] for row in cursor.fetchall()}
        else:
            schema = 'DATABASE()' if dialect == 'MySQLStore' else 'current_schema()'
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='cuentas' AND table_schema=" + schema)
            columns = {next(iter(row.values())) if isinstance(row, dict) else row[0] for row in cursor.fetchall()}
        self._legacy_account_columns = {'identificacion', 'nombres', 'apellidos'} <= columns
        if 'cliente_nro' in columns:
            return
        if not self._legacy_account_columns:
            raise ValueError('Esquema de cuentas no reconocido; no se modificaron los registros')
        kind = 'VARCHAR(255)' if dialect == 'MySQLStore' else 'TEXT REFERENCES clientes(nro)'
        cursor.execute('ALTER TABLE cuentas ADD COLUMN cliente_nro ' + kind)
        statement = 'INSERT INTO clientes (nro,identificacion,nombres,apellidos) SELECT nro,identificacion,nombres,apellidos FROM cuentas'
        if dialect == 'MySQLStore':
            statement = statement.replace('INSERT INTO', 'INSERT IGNORE INTO', 1)
        elif dialect == 'SQLiteStore':
            statement = statement.replace('INSERT INTO', 'INSERT OR IGNORE INTO', 1)
        else:
            statement += ' ON CONFLICT (nro) DO NOTHING'
        cursor.execute(statement)
        cursor.execute('UPDATE cuentas SET cliente_nro=nro WHERE cliente_nro IS NULL')

    def get_account(self, account_ref):
        mark = '?' if self.__class__.__name__ == 'SQLiteStore' else '%s'
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute('SELECT * FROM cuentas WHERE nro=' + mark, (account_ref,))
                row = cursor.fetchone()
                if row is None:
                    return None
                if isinstance(row, dict):
                    return row
                return dict(zip([column[0] for column in cursor.description], row))
            finally:
                cursor.close()
                self._connection.rollback()  # Finalizar la instantánea de esta lectura.

    def count_accounts(self):
        with self._lock:
            cursor=self._connection.cursor()
            try:
                cursor.execute('SELECT count(*) AS total FROM cuentas')
                row=cursor.fetchone()
                return int(row['total'] if isinstance(row,dict) else row[0])
            finally:
                cursor.close()
                self._connection.rollback()  # Finalizar la instantánea de esta lectura.

    def encrypted_accounts_after(self, after, limit):
        mark='?' if self.__class__.__name__=='SQLiteStore' else '%s'
        fields=('Nro','Identificacion','Nombres','Apellidos','NroCuenta','IdBanco','Saldo')
        with self._lock:
            cursor=self._connection.cursor()
            try:
                cursor.execute('SELECT c.nro,cl.identificacion,cl.nombres,cl.apellidos,c.nro_cuenta,c.id_banco,c.saldo '
                               'FROM cuentas c JOIN clientes cl ON cl.nro=c.cliente_nro WHERE c.nro > '+mark+
                               ' ORDER BY c.nro LIMIT '+mark,(after,limit))
                rows=cursor.fetchall()
                result=[]
                for row in rows:
                    if isinstance(row,dict):
                        row=[row[k] for k in ('nro','identificacion','nombres','apellidos','nro_cuenta','id_banco','saldo')]
                    result.append(dict(zip(fields,row)))
                return result
            finally:
                cursor.close()
                self._connection.rollback()  # Finalizar la instantánea de esta lectura.

    def upsert_accounts_batch(self, records):
        if not records:
            return
        dialect = self.__class__.__name__
        postgres = dialect == 'PostgreSQLStore'
        mysql = dialect == 'MySQLStore'
        mark = '%s' if postgres or mysql else '?'
        clients = [(str(r['Nro']),r['Identificacion'],r['Nombres'],r['Apellidos']) for r in records]
        accounts = [(str(r['Nro']),str(r['Nro']),r['NroCuenta'],int(r['IdBanco']),r['Saldo']) for r in records]
        account_columns = 'nro,cliente_nro,nro_cuenta,id_banco,saldo'
        if getattr(self, '_legacy_account_columns', False):
            account_columns += ',identificacion,nombres,apellidos'
            accounts = [values + (r['Identificacion'], r['Nombres'], r['Apellidos']) for values, r in zip(accounts, records)]
        def insert(cursor, table, columns, rows):
            # Recargar el mismo dataset no altera cuentas previamente confirmadas.
            names = columns.split(',')
            if mysql:
                suffix = ' ON DUPLICATE KEY UPDATE '+names[0]+'=VALUES('+names[0]+')'
            else:
                suffix = ' ON CONFLICT ('+names[0]+') DO NOTHING'
            sql = f'INSERT INTO {table} ({columns}) VALUES '
            if postgres:
                from psycopg2.extras import execute_values
                execute_values(cursor,sql+'%s'+suffix,rows,page_size=1000)
            else:
                cursor.executemany(sql+'('+','.join([mark]*len(names))+')'+suffix,rows)
        with self._lock:
            cursor = self._connection.cursor()
            try:
                insert(cursor,'clientes','nro,identificacion,nombres,apellidos',clients)
                insert(cursor,'cuentas',account_columns,accounts)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def confirm_batch(self, requests):
        if not requests:
            return []
        dialect = self.__class__.__name__
        sqlite = dialect == 'SQLiteStore'
        mark = '?' if sqlite else '%s'
        with self._lock:
            cursor = self._connection.cursor()
            try:
                if sqlite:
                    cursor.execute('BEGIN IMMEDIATE')
                refs = [r.account_ref for r in requests]
                cursor.execute('SELECT nro,codigo_verificacion,saldo_bs,tipo_cambio,convertido_at FROM cuentas WHERE nro IN ('+
                               ','.join([mark]*len(refs))+')'+('' if sqlite else ' FOR UPDATE'), refs)
                rows = cursor.fetchall()
                existing = {}
                for row in rows:
                    if isinstance(row,dict):
                        values=[row[k] for k in ('nro','codigo_verificacion','saldo_bs','tipo_cambio','convertido_at')]
                    else:
                        values=list(row)
                    existing[str(values[0])] = values
                updates=[]
                result=[]
                for request in requests:
                    row=existing.get(request.account_ref)
                    error=None
                    if row is None:
                        error='Cuenta no encontrada'
                    elif row[1] and not newer_conversion(request, row[1], row[4]) and (row[1] != request.verification_code or parse_money(row[2]) != parse_money(request.saldo_bs)
                                     or parse_money(row[3]) != parse_money(request.exchange_rate)):
                        error='Cuenta ya confirmada con otros datos'
                    if error:
                        result.append(dict(account_ref=request.account_ref,status='ERROR',detail=error))
                        continue
                    timestamp=request.converted_at
                    if dialect=='MySQLStore':
                        from datetime import timezone
                        timestamp=timestamp.astimezone(timezone.utc).replace(tzinfo=None)
                    elif sqlite:
                        timestamp=timestamp.isoformat()
                    if not row[1] or newer_conversion(request, row[1], row[4]):
                        updates.append((request.saldo_bs,request.verification_code,request.exchange_rate,timestamp,request.account_ref))
                        row[1:]=[request.verification_code,request.saldo_bs,request.exchange_rate,timestamp]
                    result.append(dict(account_ref=request.account_ref,status='CONFIRMADA',verification_code=request.verification_code,
                                       saldo_bs=str(row[2]),exchange_rate=str(row[3]),converted_at=str(row[4])))
                if updates:
                    cursor.executemany('UPDATE cuentas SET saldo_bs='+mark+',codigo_verificacion='+mark+',tipo_cambio='+mark+
                                       ',convertido_at='+mark+' WHERE nro='+mark,updates)
                self._connection.commit()
                return result
            except Exception:
                self._connection.rollback()
                raise
            finally:
                cursor.close()

    def confirm(self, request):
        result=self.confirm_batch([request])[0]
        if result['status']=='ERROR':
            if result['detail']=='Cuenta no encontrada':
                raise KeyError(result['detail'])
            raise ValueError(result['detail'])
        return result
