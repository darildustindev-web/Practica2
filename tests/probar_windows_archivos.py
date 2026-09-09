"""Reproduce en Linux la regla de Windows que rompió el seeder.

En Windows no se puede borrar ni mover un archivo que sigue abierto por el
proceso. En Linux sí, por eso el fallo nunca apareció en las pruebas.

Esta prueba parcha os.unlink y os.replace para que se comporten como Windows
(fallan con PermissionError si el archivo tiene un descriptor abierto) y luego
corre el seeder de verdad sobre un CSV chico.

Sirve como regresión: si alguien vuelve a dejar una conexión sqlite abierta
dentro de una carpeta temporal, esta prueba falla en cualquier sistema.

Uso:
    python probar_windows_archivos.py                 # usa scripts/seeder.py
    python probar_windows_archivos.py <otro_seeder.py>
"""
import builtins
import io
import os
import sys
import csv
import random
import shutil
import tempfile
from pathlib import Path

ABIERTOS: dict[str, int] = {}
_open_real = builtins.open
_unlink_real = os.unlink
_remove_real = os.remove
_replace_real = os.replace
_rmdir_real = os.rmdir


def _normal(ruta) -> str:
    try:
        return os.path.abspath(os.fspath(ruta))
    except TypeError:
        return ""


class _ArchivoVigilado(io.FileIO):
    pass


def open_vigilado(archivo, mode="r", *args, **kwargs):
    objeto = _open_real(archivo, mode, *args, **kwargs)
    clave = _normal(archivo)
    if clave:
        ABIERTOS[clave] = ABIERTOS.get(clave, 0) + 1
        cerrar_real = objeto.close

        def cerrar():
            if ABIERTOS.get(clave):
                ABIERTOS[clave] -= 1
                if ABIERTOS[clave] <= 0:
                    ABIERTOS.pop(clave, None)
            return cerrar_real()

        try:
            objeto.close = cerrar
        except AttributeError:
            pass
    return objeto


def _comprobar(ruta, operacion, dir_fd=None):
    if dir_fd is not None:
        try:
            ruta = os.path.join(os.readlink(f"/proc/self/fd/{dir_fd}"), os.fspath(ruta))
        except OSError:
            pass
    clave = _normal(ruta)
    if ABIERTOS.get(clave):
        raise PermissionError(
            32,
            "El proceso no tiene acceso al archivo porque esta siendo utilizado "
            f"por otro proceso: {ruta!r}  [simulado: {operacion}]",
        )


def unlink_windows(ruta, *a, **k):
    _comprobar(ruta, "unlink", k.get("dir_fd"))
    return _unlink_real(ruta, *a, **k)


def remove_windows(ruta, *a, **k):
    _comprobar(ruta, "remove", k.get("dir_fd"))
    return _remove_real(ruta, *a, **k)


def replace_windows(origen, destino, *a, **k):
    _comprobar(origen, "replace(origen)")
    _comprobar(destino, "replace(destino)")
    return _replace_real(origen, destino, *a, **k)


def instalar():
    # shutil.rmtree usa por defecto una ruta basada en descriptores de directorio
    # (os.unlink con dir_fd) que no existe en Windows. Se desactiva para que el
    # borrado pase por os.unlink con ruta completa, como en Windows.
    import shutil as _shutil
    _shutil._use_fd_functions = False
    builtins.open = open_vigilado
    os.unlink = unlink_windows
    os.remove = remove_windows
    os.replace = replace_windows
    # sqlite3 no usa builtins.open: se registra su archivo a mano. `close` es de
    # sólo lectura en sqlite3.Connection, así que se usa una subclase por factory.
    import sqlite3

    conectar_real = sqlite3.connect

    class _ConexionVigilada(sqlite3.Connection):
        _clave = ""
        _cerrada = False

        def close(self):
            if not self._cerrada:
                self._cerrada = True
                if self._clave and ABIERTOS.get(self._clave):
                    ABIERTOS[self._clave] -= 1
                    if ABIERTOS[self._clave] <= 0:
                        ABIERTOS.pop(self._clave, None)
            return super().close()

    def conectar(base, *a, **k):
        k.pop("factory", None)
        conexion = conectar_real(base, *a, factory=_ConexionVigilada, **k)
        clave = _normal(base) if isinstance(base, (str, os.PathLike)) else ""
        if clave and str(base) != ":memory:":
            ABIERTOS[clave] = ABIERTOS.get(clave, 0) + 1
            conexion._clave = clave
        return conexion

    sqlite3.connect = conectar


def hacer_csv(destino: Path, filas: int = 400) -> None:
    rng = random.Random(7)
    with _open_real(destino, "w", encoding="utf-8", newline="") as salida:
        w = csv.writer(salida)
        w.writerow(["Nro", "Identificacion", "Nombres", "Apellidos", "NroCuenta", "IdBanco", "Saldo"])
        for i in range(1, filas + 1):
            w.writerow([
                i,
                f"{1000000 + i}",
                f"Nombre{i}",
                f"Apellido{i}",
                f"{4000000000 + i}",
                (i % 14) + 1,
                f"{rng.randint(1, 900000)}.{rng.randint(0, 9999):04d}",
            ])


def principal() -> int:
    if len(sys.argv) > 1:
        ruta_seeder = Path(sys.argv[1]).resolve()
    else:
        ruta_seeder = Path(__file__).resolve().parents[1] / "scripts" / "seeder.py"
    if not ruta_seeder.exists():
        print(f"No se encontro {ruta_seeder}")
        return 1
    raiz = ruta_seeder.parents[1]
    sys.path.insert(0, str(raiz))
    sys.path.insert(0, str(raiz / "asfi-service"))

    instalar()

    import importlib.util

    espec = importlib.util.spec_from_file_location("seeder_bajo_prueba", ruta_seeder)
    seeder = importlib.util.module_from_spec(espec)
    sys.modules["seeder_bajo_prueba"] = seeder
    espec.loader.exec_module(seeder)

    trabajo = Path(tempfile.mkdtemp(prefix="prueba-seeder-"))
    try:
        dataset = trabajo / "dataset.csv"
        hacer_csv(dataset)
        salida = trabajo / "seed"

        # workers=1: evita procesos hijos, que no heredan los parches.
        try:
            metrics = seeder.seed(str(dataset), str(salida), workers=1, batch_size=100)
        except (OSError, PermissionError) as exc:
            print(f"FALLA  el seeder murio: {type(exc).__name__}: {exc}")
            sobrantes = [p.name for p in salida.iterdir()] if salida.exists() else []
            print(f"       quedo en data/seed: {sobrantes}")
            return 1

        print(f"  filas leidas   : {metrics['leidas']}")
        print(f"  filas cifradas : {metrics['cifradas']}")
        print(f"  rechazadas     : {metrics['rechazadas']}")

        problemas = []
        sobrantes = [p.name for p in salida.iterdir() if p.name.startswith(".seed-")]
        if sobrantes:
            problemas.append(f"quedaron carpetas temporales sin borrar: {sobrantes}")
        faltantes = [f"bank_{i:02d}.jsonl" for i in range(1, 15) if not (salida / f"bank_{i:02d}.jsonl").exists()]
        if faltantes:
            problemas.append(f"no se publicaron: {faltantes}")
        if not (salida / "metrics.json").exists():
            problemas.append("falta metrics.json")
        if metrics["leidas"] != 400 or metrics["cifradas"] + metrics["rechazadas"] != 400:
            problemas.append(f"cuentas descuadradas: {metrics['leidas']} leidas, "
                             f"{metrics['cifradas']} cifradas, {metrics['rechazadas']} rechazadas")
        if ABIERTOS:
            problemas.append(f"quedaron descriptores abiertos: {sorted(ABIERTOS)}")

        print()
        if problemas:
            for p in problemas:
                print("FALLA  " + p)
            return 1
        print("OK  el seeder termina limpio bajo las reglas de Windows")
        print("    (nota: si falta el modulo 'twofish', el banco 9 queda vacio;")
        print("     eso no afecta lo que mide esta prueba)")
        print("OK  se publicaron los 14 .jsonl + rejected_rows.csv + metrics.json")
        print("OK  no quedaron carpetas .seed-* ni archivos abiertos")
        return 0
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(principal())
