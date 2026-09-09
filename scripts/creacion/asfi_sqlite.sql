-- Esquema ASFI; ejecutar manualmente en la base elegida, sin borrar datos.
CREATE TABLE IF NOT EXISTS asfi_cuentas (
 banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL,
 saldo_usd TEXT NOT NULL, saldo_bs TEXT NOT NULL,
 tipo_cambio TEXT NOT NULL, codigo_verificacion CHAR(8) NOT NULL,
 fecha_conversion TEXT NOT NULL, estado TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY (banco_id,cuenta_id)
);
CREATE TABLE IF NOT EXISTS asfi_historial (
 banco_id INTEGER NOT NULL, cuenta_id TEXT NOT NULL,
 codigo_verificacion CHAR(8) NOT NULL, payload TEXT NOT NULL
);
