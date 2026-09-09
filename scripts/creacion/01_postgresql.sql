-- Entregable: ejecutar MANUALMENTE en el servidor correspondiente. No borra datos.
\set ON_ERROR_STOP on
-- Cada banco reside en un servidor separado. Pasar -v banco=bank_union (o bank_bcp / bank_ganadero).
SELECT format('CREATE DATABASE %I', :'banco') WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname=:'banco') \gexec
\connect :banco
CREATE TABLE IF NOT EXISTS clientes (
    nro TEXT PRIMARY KEY,
    identificacion TEXT NOT NULL,
    nombres TEXT NOT NULL,
    apellidos TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cuentas (
    nro TEXT PRIMARY KEY,
    cliente_nro TEXT NOT NULL REFERENCES clientes(nro),
    nro_cuenta TEXT NOT NULL,
    id_banco INTEGER NOT NULL,
    saldo TEXT NOT NULL,
    saldo_bs TEXT,
    codigo_verificacion CHAR(8),
    tipo_cambio TEXT,
    convertido_at TIMESTAMPTZ
);
