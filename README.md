# 🏦 Práctica 2: Plataforma Distribuida de Conversión Monetaria Interbancaria (ASFI - BCB)

Bienvenido al repositorio oficial del proyecto **Práctica 2 - Sistemas Distribuidos**. Este proyecto simula un entorno real de interoperabilidad financiera distribuida bajo restricciones monetarias en Bolivia, donde la **ASFI** procesa la conversión obligatoria de cuentas bancarias en dólares estadounidenses (USD) a bolivianos (Bs.) utilizando la cotización fluctuante del **Banco Central de Bolivia (BCB)**.

---

## 📐 1. Resumen de la Arquitectura del Sistema

El sistema consta de 3 capas principales de microservicios:

```
                                  +---------------------------------------+
                                  |     Servicio BCB (Tasa de Cambio)     |
                                  | - Cotización USD ➔ Bs. (±0.9999)      |
                                  | - Fluctuación configurable c/ 3 min   |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |     Servicio Central ASFI (Core)     |
                                  | - Barrido Paralelo Asíncrono (14 APIs)|
                                  | - Gestor de Llaves (Key Manager)      |
                                  | - Motor Criptográfico (14 Cifrados)   |
                                  | - Generador de Código Hex 8 dígitos   |
                                  | - Registro de Auditoría (Audit Log)   |
                                  | - BD Central Relacional (PostgreSQL)  |
                                  +---------+-------------------+---------+
                                            |                   |
                     +----------------------+                   +----------------------+
                     | (GET /cuentas/cifradas)                  | (GET /cuentas/cifradas)
                     | (POST /cuentas/confirmar)                | (POST /cuentas/confirmar)
                     v                                          v
      +------------------------------+           +------------------------------+
      |      Bancos Relacionales     |           |     Bancos No-Relacionales    |
      |          (1 al 7)            |           |         (8 al 14)            |
      | - Banco Unión (César)        |           | - Banco Prodem (Blowfish)    |
      | - Banco Mercantil (Atbash)   |           | - Banco Solidario (Twofish)  |
      | - BNB (Vigenère)             |           | - Banco Fortaleza (AES)      |
      | - BCP (Playfair)             |           | - Banco FIE (RSA)            |
      | - Banco BISA (Hill)          |           | - Banco PYME (ElGamal)       |
      | - Banco Ganadero (DES)       |           | - BDP (ECC - Neo4j Grafos)   |
      | - Banco Económico (3DES)     |           | - Banco N. Arg. (ChaCha20)   |
      |                              |           |                              |
      |  (PostgreSQL, MySQL, SQLite) |           | (MongoDB, Redis, Neo4j)      |
      +------------------------------+           +------------------------------+
```

---

## 👥 2. Asignación de Roles y Tareas por Integrante

### 🔵 Integrante 1 (Líder de Proyecto / Núcleo ASFI & Criptografía - Daril)
**Responsabilidades principales:**
1. **Motor Criptográfico Central (`asfi-service/crypto/`):**
   - Implementar/organizar las funciones de descifrado y cifrado para los 14 algoritmos (César, Atbash, Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, RSA, ElGamal, ECC, ChaCha20).
   - Crear el **Gestor de Llaves ASFI (Key Manager)**.
2. **Servicio Central ASFI & BD Central (`asfi-service/`):**
   - Diseñar la base de datos relacional de consolidación de ASFI (PostgreSQL).
   - Implementar el procesador de conversión USD ➔ Bs y el generador del **Código de Verificación Hexadecimal de 8 caracteres** (`0-9, A-F`).
3. **Barrido Paralelo Asíncrono & Auditoría:**
   - Desarrollar el cliente asíncrono/multihilo (`httpx`/`asyncio`) que ejecute las peticiones en paralelo a las 14 APIs bancarias simultáneamente para evitar sesgos por la fluctuación del dólar.
   - Generar el archivo/tabla de **Log de Auditoría** (Timestamp, Tasa BCB, CuentaId, BancoId, CodigoVerificacion, Estado).

---

### 🟢 Integrante 2 (Infraestructura Bancos Relacionales & Seeder)
**Responsabilidades principales:**
1. **Generador y Poblamiento de Datos (`scripts/seeder.py`):**
   - Crear el script que genera y puebla la muestra del 1% (~120,000 cuentas en total entre los 14 bancos).
   - Asegurar que cada cuenta sea guardada en su correspondiente BD bancaria con sus datos sensibles previamente cifrados.
2. **Motores de BD Relacionales (Bancos 1 al 7):**
   - Configurar los motores relacionales (mínimo 3 distintas tecnologías: **PostgreSQL**, **MySQL**, **MariaDB/SQLite**).
   - Mapear las bases de datos para los Bancos 1 al 7:
     1. Banco Unión S.A. (César)
     2. Banco Mercantil Santa Cruz S.A. (Atbash)
     3. Banco Nacional de Bolivia (BNB) (Vigenère)
     4. Banco de Crédito de Bolivia (BCP) (Playfair)
     5. Banco BISA S.A. (Hill)
     6. Banco Ganadero S.A. (DES)
     7. Banco Económico S.A. (3DES)
3. **APIs Bancarias (Bancos 1 al 7):**
   - Exponer endpoints para la entrega de datos cifrados y la recepción/actualización del código de verificación de 8 dígitos hexadecimales.

---

### 🔴 Integrante 3 (BDs NoSQL, Grafo Neo4j, Servicio BCB & Reportes)
**Responsabilidades principales:**
1. **Servicio BCB (Fluctuación del Dólar) (`bcb-service/`):**
   - Desarrollar el microservicio mock del BCB que fluctúe la cotización del dólar cada **3 minutos (configurable)** en **±0.9999** con **4 decimales** de precisión.
2. **BDs No-Relacionales y Base de Datos de Grafos (Bancos 8 al 14):**
   - Configurar motores NoSQL (ej. **MongoDB**, **Redis**).
   - **Requisito Crítico (20 pts):** Implementar **1 Base de Datos orientada a Grafos en Neo4j** para uno de los bancos (ej. BDP) con nodos `Cliente` y `Cuenta` y relación `TIENE_CUENTA`.
   - Mapear las BDs de los Bancos 8 al 14:
     8. Banco Prodem S.A. (Blowfish)
     9. Banco Solidario S.A. (Twofish)
     10. Banco Fortaleza S.A. (AES)
     11. Banco FIE S.A. (RSA)
     12. Banco PYME de la Comunidad S.A. (ElGamal)
     13. Banco de Desarrollo Productivo S.A.M. (ECC - Neo4j)
     14. Banco de la Nación Argentina (ChaCha20)
3. **APIs Bancarias (Bancos 8 al 14) & Consultas (40 pts):**
   - Exponer endpoints para bancos 8 al 14.
   - Escribir los **8 scripts de consulta SQL/NoSQL** requeridos por la guía de la práctica para verificación de saldo y auditoría sin uso de IA durante la defensa.

---

## 📊 3. Mapeo Oficial de Entidades Financieras y Algoritmos

| ID | Banco | Nro. Cuentas (100%) | Nro. Cuentas (1% Muestra) | Algoritmo de Cifrado | Motor de Base de Datos Recomendado |
|---|---|---|---|---|---|
| 1 | Banco Unión S.A. | 2,247,210 | 22,472 | Cifrado César | PostgreSQL |
| 2 | Banco Mercantil Santa Cruz S.A. | 1,997,520 | 19,975 | Cifrado Atbash | MySQL |
| 3 | Banco Nacional de Bolivia (BNB) | 1,498,140 | 14,981 | Cifrado Vigenère | MariaDB / SQLite |
| 4 | Banco de Crédito de Bolivia (BCP) | 1,398,264 | 13,983 | Cifrado Playfair | PostgreSQL |
| 5 | Banco BISA S.A. | 1,048,698 | 10,487 | Cifrado Hill | MySQL |
| 6 | Banco Ganadero S.A. | 948,822 | 9,488 | Cifrado DES | PostgreSQL |
| 7 | Banco Económico S.A. | 848,946 | 8,489 | Cifrado 3DES | MySQL |
| 8 | Banco Prodem S.A. | 749,070 | 7,491 | Blowfish | MongoDB |
| 9 | Banco Solidario S.A. | 549,318 | 5,493 | Twofish | MongoDB |
| 10 | Banco Fortaleza S.A. | 349,566 | 3,496 | AES | Redis / MongoDB |
| 11 | Banco FIE S.A. | 399,504 | 3,995 | RSA | MongoDB |
| 12 | Banco PYME de la Comunidad S.A. | 224,721 | 2,247 | ElGamal | SQLite / MongoDB |
| 13 | Banco de Desarrollo Productivo S.A.M. | 99,876 | 999 | ECC | **Neo4j (BD de Grafos)** |
| 14 | Banco de la Nación Argentina | 19,975 | 200 | ChaCha20 | MongoDB |

---

## 📂 4. Estructura de Directorios del Proyecto

```text
Practica2/
├── README.md                              # Este documento
├── 01 - Practica 2 Algoritmos...md        # Especificaciones del docente
├── docker-compose.yml                     # Orquestador de contenedores (BDs y servicios)
├── bcb-service/                           # Microservicio BCB (Tipo de Cambio)
│   ├── main.py                            # FastAPI app
│   └── requirements.txt
├── asfi-service/                          # Servicio Central ASFI
│   ├── main.py                            # FastAPI app y Orquestador de Barrido
│   ├── crypto/                            # Módulo central de algoritmos de cifrado/descifrado
│   │   ├── ciphers.py                     # César, Atbash, Vigenère, Playfair, Hill, AES, RSA, etc.
│   │   └── key_manager.py                 # Gestión de llaves ASFI
│   ├── database.py                        # Conexión BD ASFI
│   ├── audit_logger.py                    # Generador de Logs de auditoría
│   └── requirements.txt
├── banks-services/                        # APIs de las 14 Entidades Financieras
│   ├── common/                            # Código común para las APIs bancarias
│   │   └── bank_router.py                 # Endpoints genéricos GET /cuentas y POST /confirmar
│   ├── bank_01_union/                     # Microservicio Banco Unión
│   ├── bank_02_mercantil/
│   ├── ...
│   └── bank_14_nacion_argentina/
├── scripts/                               # Scripts de apoyo y utilidad
│   ├── seeder.py                          # Script de poblamiento del 1% (~120,000 cuentas)
│   └── queries.sql                        # Consultas de verificación
└── docs/                                  # Documentación adicional
```

---

## 🤖 5. Guía para Consultar a la IA durante el Desarrollo

Para que todos los integrantes puedan usar asistentes de IA de forma consistente y sin romper el código de los demás, **sigan este formato al hacer preguntas**:

### 💡 Ejemplo de Prompt para pedir ayuda a la IA:
> *"Estoy trabajando en la **Práctica 2 de Sistemas Distribuidos (ASFI/BCB)**. Mi rol es el **[Rol: Integrante 1 / 2 / 3]**. Revisa el archivo `README.md` del repositorio para entender la estructura. Necesito implementar la clase/función `[Nombre de la función/API]` siguiendo el patrón establecido en `[Ruta del archivo]`..."*

---

## 🛠️ 6. Cómo Levantar el Proyecto Localmente

### Prerrequisitos
- Docker y Docker Compose instalados.
- Python 3.11+ instalado.

### Pasos
1. **Clonar el repositorio y entrar al proyecto:**
   ```bash
   git clone <URL_DEL_REPOSITO>
   cd Practica2
   ```

2. **Levantar la infraestructura con Docker Compose:**
   ```bash
   docker-compose up -d --build
   ```

3. **Poblar las bases de datos con la muestra del 1%:**
   ```bash
   python scripts/seeder.py
   ```

4. **Probar el Barrido Paralelo de la ASFI:**
   ```bash
   curl -X POST http://localhost:8000/api/asfi/ejecutar-conversion
   ```

---
*Desarrollado para la materia de Sistemas Distribuidos - Práctica 2.*
