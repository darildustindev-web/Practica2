// Ejecutar manualmente contra la base neo4j. No inserta cuentas ficticias.
CREATE CONSTRAINT cuenta_id_unique IF NOT EXISTS FOR (cu:Cuenta) REQUIRE cu.cuentaId IS UNIQUE;
CREATE CONSTRAINT cliente_id_unique IF NOT EXISTS FOR (cl:Cliente) REQUIRE cl.clienteId IS UNIQUE;
