-- =====================================================================
-- BD CENTRAL ASFI - Esquema tal como lo define el enunciado (PostgreSQL)
-- =====================================================================
-- El enunciado especifica literalmente estas dos tablas:
--
--   Bancos(BancoId INT PRIMARY KEY, Nombre VARCHAR(100), AlgoritmoEncriptacion VARCHAR(50))
--   Cuentas(CuentaId BIGINT PRIMARY KEY, BancoId INT, SaldoUSD DECIMAL(18,4),
--           SaldoBs DECIMAL(18,4), FechaConversion DATETIME, CodigoVerificacion CHAR(8),
--           FOREIGN KEY (BancoId) REFERENCES Bancos(BancoId))
--
-- La tabla física que escribe el servicio ASFI es `asfi_cuentas`, que además
-- guarda el estado de la transacción y el payload de auditoría (información
-- que el enunciado no pide pero es necesaria para la trazabilidad y el
-- reintento seguro). Para no duplicar datos ni romper el servicio:
--
--   * `Bancos`  se crea como TABLA REAL con el catálogo de las 14 entidades.
--   * `Cuentas` se crea como VISTA sobre asfi_cuentas, exponiendo exactamente
--     los nombres y tipos de columna que pide el enunciado.
--
-- Así el docente puede consultar `Bancos` y `Cuentas` tal como los definió,
-- y el sistema sigue escribiendo en su tabla real sin cambios.
--
-- Ejecutar:  psql -h 127.0.0.1 -p 5434 -U asfi_user -d asfi_db -f asfi_vistas_enunciado.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- Tablas base que escribe el servicio ASFI.
-- Se crean aquí también (IF NOT EXISTS) para que este script funcione sobre
-- una base recién creada, antes de que la ASFI haya corrido por primera vez.
-- Son exactamente las mismas que crea asfi-service/journal.py: si ya existen,
-- estas sentencias no hacen nada y no se pierde ningún dato.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asfi_cuentas (
    banco_id INTEGER NOT NULL,
    cuenta_id TEXT NOT NULL,
    saldo_usd DECIMAL(18,4) NOT NULL,
    saldo_bs DECIMAL(18,4) NOT NULL,
    tipo_cambio DECIMAL(18,4) NOT NULL,
    codigo_verificacion CHAR(8) NOT NULL,
    fecha_conversion TEXT NOT NULL,
    estado TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (banco_id, cuenta_id)
);

CREATE TABLE IF NOT EXISTS asfi_historial (
    banco_id INTEGER NOT NULL,
    cuenta_id TEXT NOT NULL,
    codigo_verificacion CHAR(8) NOT NULL,
    payload TEXT NOT NULL
);


-- ---------------------------------------------------------------------
-- Tabla Bancos: catálogo de las 14 entidades financieras participantes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Bancos (
    BancoId               INT PRIMARY KEY,
    Nombre                VARCHAR(100) NOT NULL,
    AlgoritmoEncriptacion VARCHAR(50)  NOT NULL
);

INSERT INTO Bancos (BancoId, Nombre, AlgoritmoEncriptacion) VALUES
    (1,  'Banco Unión S.A.',                      'César'),
    (2,  'Banco Mercantil Santa Cruz S.A.',       'Atbash'),
    (3,  'Banco Nacional de Bolivia S.A. (BNB)',  'Vigenère'),
    (4,  'Banco de Crédito de Bolivia S.A. (BCP)','Playfair'),
    (5,  'Banco BISA S.A.',                       'Hill'),
    (6,  'Banco Ganadero S.A.',                   'DES'),
    (7,  'Banco Económico S.A.',                  '3DES'),
    (8,  'Banco Prodem S.A.',                     'Blowfish'),
    (9,  'Banco Solidario S.A.',                  'Twofish'),
    (10, 'Banco Fortaleza S.A.',                  'AES'),
    (11, 'Banco FIE S.A.',                        'RSA'),
    (12, 'Banco PYME de la Comunidad S.A.',       'ElGamal'),
    (13, 'Banco de Desarrollo Productivo S.A.M.', 'ECC'),
    (14, 'Banco de la Nación Argentina',          'ChaCha20')
ON CONFLICT (BancoId) DO UPDATE
    SET Nombre = EXCLUDED.Nombre,
        AlgoritmoEncriptacion = EXCLUDED.AlgoritmoEncriptacion;


-- ---------------------------------------------------------------------
-- Vista Cuentas: presenta asfi_cuentas con el contrato del enunciado
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW Cuentas AS
SELECT
    CAST(cuenta_id AS BIGINT)                    AS CuentaId,
    banco_id                                     AS BancoId,
    CAST(saldo_usd AS DECIMAL(18,4))             AS SaldoUSD,
    CAST(saldo_bs  AS DECIMAL(18,4))             AS SaldoBs,
    CAST(fecha_conversion AS TIMESTAMPTZ)        AS FechaConversion,
    CAST(codigo_verificacion AS CHAR(8))         AS CodigoVerificacion,
    estado                                       AS Estado
FROM asfi_cuentas;


-- ---------------------------------------------------------------------
-- Comprobaciones (ejecutar después de un barrido)
-- ---------------------------------------------------------------------

-- Catálogo de bancos con su algoritmo
SELECT * FROM Bancos ORDER BY BancoId;

-- Consolidado por banco usando el contrato del enunciado
SELECT b.BancoId,
       b.Nombre,
       b.AlgoritmoEncriptacion,
       count(c.CuentaId)  AS Cuentas,
       sum(c.SaldoUSD)    AS TotalUSD,
       sum(c.SaldoBs)     AS TotalBs
FROM Bancos b
LEFT JOIN Cuentas c ON c.BancoId = b.BancoId
GROUP BY b.BancoId, b.Nombre, b.AlgoritmoEncriptacion
ORDER BY b.BancoId;

-- Integridad referencial: ninguna cuenta debe apuntar a un banco inexistente
SELECT count(*) AS cuentas_con_banco_desconocido
FROM Cuentas c
LEFT JOIN Bancos b ON b.BancoId = c.BancoId
WHERE b.BancoId IS NULL;
