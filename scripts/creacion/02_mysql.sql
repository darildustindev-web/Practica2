-- Entregable: ejecutar MANUALMENTE en el servidor correspondiente. No borra datos.
-- Elegir el banco del servidor y reemplazar bank_mercantil si corresponde a BISA/Económico.
CREATE DATABASE IF NOT EXISTS bank_mercantil;
USE bank_mercantil;
CREATE TABLE IF NOT EXISTS clientes (
    nro VARCHAR(255) PRIMARY KEY,
    identificacion TEXT NOT NULL,
    nombres TEXT NOT NULL,
    apellidos TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cuentas (
    nro VARCHAR(255) PRIMARY KEY,
    cliente_nro VARCHAR(255) NOT NULL,
    nro_cuenta TEXT NOT NULL,
    id_banco INT NOT NULL,
    saldo TEXT NOT NULL,
    saldo_bs TEXT,
    codigo_verificacion CHAR(8),
    tipo_cambio TEXT,
    convertido_at DATETIME(6),
    INDEX idx_cuentas_cliente (cliente_nro),
    CONSTRAINT fk_cuentas_cliente FOREIGN KEY (cliente_nro)
        REFERENCES clientes(nro)
);
