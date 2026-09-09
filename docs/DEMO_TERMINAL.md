# Demostración sin interfaz gráfica

Desde la carpeta del proyecto, iniciar bases y APIs (no carga ni borra datos):

```bash
docker compose up -d
.venv/bin/python scripts/run_panel.py
```

Mantener esa terminal abierta. El nombre del lanzador es histórico: también sirve para usar exclusivamente las APIs desde terminal.

En otra terminal:

```bash
.venv/bin/python scripts/demo_terminal.py estado
.venv/bin/python scripts/demo_terminal.py errores --bancos 4 5
.venv/bin/python scripts/demo_terminal.py validar-cifrados --bancos 4 5
.venv/bin/python scripts/demo_terminal.py intervalo 1
.venv/bin/python scripts/demo_terminal.py ejecutar --barridos 2
```

`ejecutar` actualiza las conversiones reales del entorno local. Muestra progreso cada segundo y totales por banco al terminar. Detiene la secuencia si hay errores. El intervalo modifica BCB; los barridos son secuenciales y los bancos trabajan en paralelo dentro de cada barrido.

Para verificar una cuenta, sustituir BANCO y REFERENCIA por su banco y Nro del dataset:

```bash
.venv/bin/python scripts/demo_terminal.py verificar BANCO REFERENCIA
```

Se comparan saldo, tasa y código entre ASFI y el banco. Para demostrar recotización, verificar la misma cuenta antes y después de otro barrido. El saldo USD original permanece y el nuevo resultado se calcula desde él. Las pendientes se recuperan con su operación original antes de recotizarse en otro barrido.

`errores` lee el historial acumulado local, incluso sin servicios encendidos; los eventos antiguos no representan necesariamente errores actuales. `estado` muestra la ejecución del servidor actual y una muestra reciente de errores.

Los errores históricos «Formato de cifrado Playfair/Hill no reconocido» requieren regenerar desde el dataset original con el cifrador vigente. No se debe forzar el descifrado antiguo ni borrar las bases como tratamiento genérico. Los archivos de `data/seed-terminal` están separados de `data/seed`.
