# Correcciones y entregables

## Twofish

Los nuevos datos del banco 9 usan Twofish-256 real en modo CBC, IV aleatorio por campo, relleno PKCS#7 y HMAC-SHA256 con clave de autenticación derivada y separada. El prefijo `TF1:` identifica el formato. La biblioteca base es [twofish 0.3.0](https://pypi.org/project/twofish/0.3.0/), implementación de Niels Ferguson. El puente ctypes local conserva su licencia BSD y usa importlib en lugar del módulo imp eliminado en Python 3.12. Se prueban vectores conocidos de 128/256 bits; el backend además comprueba vectores de 128/192/256 bits al importarse.

Instalación en un entorno nuevo: `.venv/bin/python -m pip install -r requirements.txt`. La dependencia contiene una extensión C y puede requerir compilador y cabeceras de Python.

Las cuentas existentes NO se reescribieron. Los textos sin prefijo del banco 9 se leen como AES legado exclusivamente por compatibilidad; no se presentan como Twofish. La auditoría de cuentas descifradas identifica `cifrado_origen` como TWOFISH_TF1 o LEGACY_AES_O_MIXTO. Para una demostración de Twofish real se requiere generar y cargar un dataset nuevo en un entorno preparado: recargar con inserciones que preservan registros no reemplaza el cifrado de cuentas existentes.

## Auditoría

Cada nueva ejecución de ASFI genera un UUID `barrido_id`. Todos sus eventos JSONL incluyen `audit_timestamp` UTC. Hay INICIO_BARRIDO, FIN_BARRIDO con resultados/tiempos y FALLO_BARRIDO. Los eventos de cuenta conservan banco, referencia, estado y motivo; se omiten datos personales completos. Para fallos HTTP recuperables se registra etapa, categoría, estado HTTP si existe y reintentable. Los reportes nuevos de seeder y carga incorporan fecha e `ejecucion_id` (propio de la generación/carga).

Consultar ID: `.venv/bin/python scripts/demo_terminal.py estado`.

Filtrar: `.venv/bin/python scripts/demo_terminal.py errores --barrido ID --bancos 1 2`.

Los logs antiguos no se modificaron: no es posible atribuirles retrospectivamente un UUID exacto. `timestamp` de una cuenta sigue siendo la fecha de la operación; `audit_timestamp` es la fecha del evento de auditoría. Un reintento conserva código y tasa aunque aparezca en un barrido nuevo. El JSONL sigue siendo acumulativo y no incluye rotación automática.

## Creación de bases

Ver [scripts/creacion/README.md](../scripts/creacion/README.md). Hay cinco scripts principales para los motores solicitados, un complemento Redis y variantes de ASFI para PostgreSQL/SQLite.

**Los scripts de creación solo se escribieron y revisaron estáticamente. No se ejecutaron.** No están enlazados al arranque automático y no cambian las bases actuales.
