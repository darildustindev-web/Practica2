"""Compatibilidad Windows / Linux para bloqueo de archivos y medición de memoria.

El proyecto usaba `fcntl` y `resource`, que existen únicamente en Unix. En
Windows el servicio ASFI ni siquiera llegaba a importarse. Este módulo ofrece
las mismas garantías en los dos sistemas:

  * Windows: LockFileEx/UnlockFileEx de kernel32 vía ctypes. Soporta bloqueo
    compartido y exclusivo igual que flock, sin dependencias externas
    (no hace falta instalar pywin32).
  * Linux/macOS: fcntl.flock, exactamente como antes.

Por qué hace falta bloqueo de verdad y no un "no-op" en Windows:
  - El seeder toma un bloqueo EXCLUSIVO mientras publica los .jsonl.
  - Los cargadores toman un bloqueo COMPARTIDO para no leer un dataset a medio
    escribir; `scripts/load_all.py` corre 14 cargadores en paralelo, así que
    varios compartidos tienen que poder convivir.
  - La ASFI toma un bloqueo EXCLUSIVO no bloqueante para impedir dos barridos
    simultáneos, y otro sobre el log de auditoría para que dos procesos no
    entremezclen líneas.
"""
from __future__ import annotations

import os
import sys

ES_WINDOWS = os.name == "nt"

# Modos, con los mismos nombres que fcntl para que el código lea igual.
COMPARTIDO = "compartido"
EXCLUSIVO = "exclusivo"


if ES_WINDOWS:  # pragma: no cover - rama de Windows
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _RANGO_BAJO = 0xFFFFFFFF
    _RANGO_ALTO = 0xFFFFFFFF

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.LockFileEx.restype = wintypes.BOOL
    _kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED),
    ]
    _kernel32.UnlockFileEx.restype = wintypes.BOOL

    def _handle(archivo):
        return msvcrt.get_osfhandle(archivo.fileno())

    def bloquear(archivo, modo=EXCLUSIVO, bloqueante=True) -> None:
        banderas = 0
        if modo == EXCLUSIVO:
            banderas |= _LOCKFILE_EXCLUSIVE_LOCK
        if not bloqueante:
            banderas |= _LOCKFILE_FAIL_IMMEDIATELY
        solape = _OVERLAPPED()
        if not _kernel32.LockFileEx(_handle(archivo), banderas, 0,
                                    _RANGO_BAJO, _RANGO_ALTO, ctypes.byref(solape)):
            error = ctypes.get_last_error()
            # ERROR_LOCK_VIOLATION (33) / ERROR_IO_PENDING (997): otro proceso lo tiene.
            raise BlockingIOError(error, f"No se pudo bloquear el archivo (error de Windows {error})")

    def desbloquear(archivo) -> None:
        solape = _OVERLAPPED()
        _kernel32.UnlockFileEx(_handle(archivo), 0, _RANGO_BAJO, _RANGO_ALTO,
                               ctypes.byref(solape))

    class _CONTADORES(ctypes.Structure):
        """PROCESS_MEMORY_COUNTERS de psapi.h."""

        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # GetCurrentProcess devuelve un HANDLE (64 bits en un Windows de 64 bits).
    # Sin declarar restype, ctypes lo trata como int de 32 bits y el
    # pseudo-handle llega truncado: GetProcessMemoryInfo falla en silencio y la
    # medición de memoria daba siempre 0.0 MiB. Lo mismo con los argtypes.
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    def _cargar_contador_memoria():
        """Devuelve la función GetProcessMemoryInfo ya declarada, o None."""
        for biblioteca, nombre in (("kernel32", "K32GetProcessMemoryInfo"),
                                   ("psapi", "GetProcessMemoryInfo")):
            try:
                dll = _kernel32 if biblioteca == "kernel32" else ctypes.WinDLL(biblioteca, use_last_error=True)
                funcion = getattr(dll, nombre)
            except (AttributeError, OSError):
                continue
            funcion.argtypes = [wintypes.HANDLE, ctypes.POINTER(_CONTADORES), wintypes.DWORD]
            funcion.restype = wintypes.BOOL
            return funcion
        return None

    _contador_memoria = _cargar_contador_memoria()

    def memoria_maxima_mib() -> float:
        if _contador_memoria is None:
            return 0.0
        try:
            contadores = _CONTADORES()
            contadores.cb = ctypes.sizeof(_CONTADORES)
            if _contador_memoria(_kernel32.GetCurrentProcess(),
                                 ctypes.byref(contadores), contadores.cb):
                return round(contadores.PeakWorkingSetSize / (1024 * 1024), 2)
        except Exception:
            pass
        return 0.0

else:
    import fcntl

    def bloquear(archivo, modo=EXCLUSIVO, bloqueante=True) -> None:
        banderas = fcntl.LOCK_EX if modo == EXCLUSIVO else fcntl.LOCK_SH
        if not bloqueante:
            banderas |= fcntl.LOCK_NB
        fcntl.flock(archivo, banderas)

    def desbloquear(archivo) -> None:
        fcntl.flock(archivo, fcntl.LOCK_UN)

    def memoria_maxima_mib() -> float:
        import resource
        uso = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux informa en KiB; macOS en bytes.
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(uso / divisor, 2)


def autoprueba() -> bool:
    """Comprueba que el bloqueo funciona en este sistema. Devuelve True si pasa.

    Se usa desde scripts/windows/Verificar-Entorno.ps1 para confirmar que el
    proyecto puede correr en la máquina antes de la demostración.
    """
    import tempfile
    from pathlib import Path

    carpeta = Path(tempfile.mkdtemp(prefix="asfi-lock-"))
    ruta = carpeta / "prueba.lock"
    try:
        # 1) Exclusivo no bloqueante: debe conseguirse.
        with ruta.open("a") as primero:
            bloquear(primero, EXCLUSIVO, bloqueante=False)

            # 2) Un segundo exclusivo sobre el mismo archivo debe fallar.
            with ruta.open("a") as segundo:
                try:
                    bloquear(segundo, EXCLUSIVO, bloqueante=False)
                except BlockingIOError:
                    pass
                else:
                    print("FALLO: se concedieron dos bloqueos exclusivos a la vez")
                    return False
            desbloquear(primero)

        # 3) Dos compartidos deben convivir (los 14 cargadores en paralelo).
        with ruta.open("a") as uno, ruta.open("a") as dos:
            bloquear(uno, COMPARTIDO, bloqueante=False)
            try:
                bloquear(dos, COMPARTIDO, bloqueante=False)
            except BlockingIOError:
                print("FALLO: dos bloqueos compartidos no pudieron convivir")
                return False
            desbloquear(uno)
            desbloquear(dos)

        print(f"Bloqueo de archivos OK ({'Windows' if ES_WINDOWS else 'Unix'})")
        print(f"Memoria máxima medible: {memoria_maxima_mib()} MiB")
        return True
    finally:
        try:
            ruta.unlink(missing_ok=True)
            carpeta.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(0 if autoprueba() else 1)
