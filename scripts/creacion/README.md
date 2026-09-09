# Scripts de creación — entregables, no ejecutados

Los cinco entregables principales son 01 PostgreSQL, 02 MySQL, 03 SQLite, 04 MongoDB y 05 Neo4j. Se incluye el complemento 06 Redis porque el proyecto utiliza seis motores, y dos variantes de esquema ASFI (usar únicamente la correspondiente).

Estos archivos NO se incorporan al lanzador ni se ejecutan automáticamente. No se han usado en las bases de la demostración. Son para una instalación nueva; CREATE IF NOT EXISTS no migra una tabla antigua incompatible.

- PostgreSQL: cada banco vive en su propio servidor del Compose. Ejecutar manualmente 01 con psql conectado a `postgres`, pasando `-v banco=bank_union`, `bank_bcp` o `bank_ganadero` según servidor. Requiere permiso CREATEDB. El creador es propietario; si se usa un administrador diferente al usuario de la API, concederle permisos antes de usar la aplicación.
- MySQL: 02 incluye `bank_mercantil`. Para BISA o Económico seleccionar previamente `bank_bisa` o `bank_economico` en las dos líneas iniciales. Ejecutar en su servidor correspondiente con permiso de creación. Los usuarios/passwords los configura Compose, no estos scripts.
- SQLite: 03 acepta `--archivo RUTA`. No ejecutar contra `data/asfi.sqlite`: es el esquema bancario.
- MongoDB: 04 crea las colecciones e índices en las cinco bases. Se ejecuta con mongosh.
- Neo4j: 05 crea restricciones en la base neo4j seleccionada; los nodos se crean al poblar. Se ejecuta con cypher-shell.
- Redis: 06 selecciona la base lógica; las claves se crean durante el poblamiento. No existe CREATE DATABASE equivalente a SQL.
- ASFI PostgreSQL: `asfi_postgresql.sql` crea la base y sus tablas con psql; requiere CREATEDB si no existe.
- ASFI SQLite: `asfi_sqlite.sql` contiene las tablas para un archivo SQLite seleccionado por el usuario. En la demostración actual ASFI usa SQLite por defecto.

No hay DROP, TRUNCATE, DELETE ni carga de cuentas en estos entregables. Revisar conexión y permisos antes de su uso manual.
