\set ON_ERROR_STOP on
SELECT 'CREATE DATABASE asfi_db' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='asfi_db') \gexec
\connect asfi_db
-- Esquema ASFI; ejecutar manualmente en la base elegida, sin borrar datos.
CREATE TABLE IF NOT EXISTS asfi_cuentas (
 banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL,
 saldo_usd DECIMAL(18,4) NOT NULL, saldo_bs DECIMAL(18,4) NOT NULL,
 tipo_cambio DECIMAL(18,4) NOT NULL, codigo_verificacion CHAR(8) NOT NULL,
 fecha_conversion TEXT NOT NULL, estado TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY (banco_id,cuenta_id)
);
CREATE TABLE IF NOT EXISTS asfi_historial (
 banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL,
 codigo_verificacion CHAR(8) NOT NULL, payload TEXT NOT NULL
);
