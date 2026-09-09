"""Autenticación y protección de la comunicación entre nodos ASFI <-> Bancos.

Cubre las "Consideraciones de Seguridad" del enunciado que no puede resolver
el cifrado de los datos en reposo:

  * Suplantación de identidad (Spoofing): cada petición viaja firmada con
    HMAC-SHA256 usando un secreto compartido que sólo conocen la ASFI y las
    entidades financieras. Un tercero no puede fabricar una confirmación.
  * Intercepción y manipulación en tránsito (MITM): la firma cubre el método,
    la ruta y el cuerpo completo. Si un atacante cambia un solo carácter del
    saldo o del código de verificación, la firma deja de validar.
  * Ataques de repetición (Replay): cada petición lleva un nonce único y una
    marca de tiempo. Se rechaza toda petición fuera de la ventana temporal y
    todo nonce ya visto dentro de esa ventana.
  * Manipulación del tipo de cambio: la firma protege el cuerpo donde viaja
    `exchange_rate`; además ASFI valida contra el BCB la frescura y el rango
    de la cotización antes de usarla (ver asfi-service/main.py).

Se activa SÓLO si existe la variable de entorno ASFI_HMAC_SECRET. Sin ella el
sistema se comporta exactamente igual que antes (útil para clase y pruebas).
Para la defensa basta exportar el secreto en ASFI y en los bancos.

Nota honesta sobre TLS: esto autentica e íntegra los mensajes, pero no cifra
el canal. Para confidencialidad en tránsito el despliegue debe ir detrás de
HTTPS/TLS (o de un túnel), lo que se configura fuera de la aplicación.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Iterable

CABECERA_FIRMA = "X-ASFI-Signature"
CABECERA_NONCE = "X-ASFI-Nonce"
CABECERA_FECHA = "X-ASFI-Timestamp"
CABECERA_NODO = "X-ASFI-Node"

VENTANA_SEGUNDOS = int(os.getenv("ASFI_HMAC_WINDOW", "120"))


def secreto_configurado() -> str | None:
    """Devuelve el secreto compartido, o None si la protección está apagada."""
    valor = (os.getenv("ASFI_HMAC_SECRET") or "").strip()
    return valor or None


def _mensaje(metodo: str, ruta: str, cuerpo: bytes, nonce: str, fecha: str, nodo: str) -> bytes:
    cuerpo_hash = hashlib.sha256(cuerpo or b"").hexdigest()
    return "\n".join([metodo.upper(), ruta, cuerpo_hash, nonce, fecha, nodo]).encode("utf-8")


def firmar(secreto: str, metodo: str, ruta: str, cuerpo: bytes,
           nonce: str, fecha: str, nodo: str = "asfi") -> str:
    """Calcula la firma HMAC-SHA256 de una petición."""
    return hmac.new(secreto.encode("utf-8"),
                    _mensaje(metodo, ruta, cuerpo, nonce, fecha, nodo),
                    hashlib.sha256).hexdigest()


def cabeceras_de_firma(metodo: str, ruta: str, cuerpo: bytes, nodo: str = "asfi") -> dict[str, str]:
    """Cabeceras listas para adjuntar a una petición saliente.

    Devuelve {} si la protección no está activada, para no alterar el
    comportamiento por defecto del sistema.
    """
    secreto = secreto_configurado()
    if not secreto:
        return {}
    nonce = secrets.token_hex(16)
    fecha = str(int(time.time()))
    return {
        CABECERA_FIRMA: firmar(secreto, metodo, ruta, cuerpo, nonce, fecha, nodo),
        CABECERA_NONCE: nonce,
        CABECERA_FECHA: fecha,
        CABECERA_NODO: nodo,
    }


class RegistroDeNonces:
    """Recuerda los nonces vistos para rechazar repeticiones.

    Sólo guarda los de la ventana vigente: la memoria no crece sin control
    aunque el sistema procese millones de peticiones.
    """

    def __init__(self, ventana: int = VENTANA_SEGUNDOS):
        self.ventana = ventana
        self._vistos: dict[str, float] = {}
        self._lock = threading.Lock()

    def registrar(self, nonce: str, ahora: float | None = None) -> bool:
        """True si el nonce es nuevo; False si ya se había usado (replay)."""
        ahora = time.time() if ahora is None else ahora
        with self._lock:
            limite = ahora - self.ventana
            if len(self._vistos) > 10000:
                self._vistos = {n: t for n, t in self._vistos.items() if t > limite}
            anterior = self._vistos.get(nonce)
            if anterior is not None and anterior > limite:
                return False
            self._vistos[nonce] = ahora
            return True


_registro_global = RegistroDeNonces()


class ErrorDeSeguridad(Exception):
    """Petición rechazada por firma, nonce o marca de tiempo inválidos."""

    def __init__(self, motivo: str, codigo: int = 401):
        super().__init__(motivo)
        self.motivo = motivo
        self.codigo = codigo


def verificar(metodo: str, ruta: str, cuerpo: bytes, cabeceras,
              registro: RegistroDeNonces | None = None,
              ahora: float | None = None) -> None:
    """Valida una petición entrante. Lanza ErrorDeSeguridad si no es legítima.

    No hace nada si la protección está desactivada.
    """
    secreto = secreto_configurado()
    if not secreto:
        return

    def leer(nombre: str) -> str:
        for clave in (nombre, nombre.lower()):
            valor = cabeceras.get(clave) if hasattr(cabeceras, "get") else None
            if valor:
                return str(valor)
        return ""

    firma = leer(CABECERA_FIRMA)
    nonce = leer(CABECERA_NONCE)
    fecha = leer(CABECERA_FECHA)
    nodo = leer(CABECERA_NODO) or "asfi"

    if not firma or not nonce or not fecha:
        raise ErrorDeSeguridad("Petición sin firma, nonce o marca de tiempo")

    # 1) Ventana temporal: frena repeticiones antiguas y relojes desfasados.
    ahora = time.time() if ahora is None else ahora
    try:
        enviado = int(fecha)
    except ValueError as exc:
        raise ErrorDeSeguridad("Marca de tiempo inválida") from exc
    if abs(ahora - enviado) > VENTANA_SEGUNDOS:
        raise ErrorDeSeguridad("Petición fuera de la ventana temporal permitida (posible replay)")

    # 2) Firma: autentica el origen y protege el contenido (spoofing / MITM).
    esperada = firmar(secreto, metodo, ruta, cuerpo, nonce, fecha, nodo)
    if not hmac.compare_digest(esperada, firma):
        raise ErrorDeSeguridad("Firma inválida: el mensaje fue alterado o el emisor no es legítimo")

    # 3) Nonce: una misma petición firmada no puede reproducirse dos veces.
    if not (registro or _registro_global).registrar(nonce, ahora):
        raise ErrorDeSeguridad("Nonce ya utilizado (ataque de repetición detectado)")


def instalar_middleware(app, rutas_protegidas: Iterable[str] = ("/api/banco",)) -> bool:
    """Protege las rutas indicadas de una app FastAPI.

    Devuelve True si quedó activa, False si la protección está apagada.
    Se llama desde el arranque de cada servicio bancario.
    """
    if not secreto_configurado():
        return False

    from fastapi.responses import JSONResponse
    prefijos = tuple(rutas_protegidas)

    @app.middleware("http")
    async def _verificar_firma(request, call_next):
        ruta = request.url.path
        if not ruta.startswith(prefijos):
            return await call_next(request)
        cuerpo = await request.body()
        try:
            verificar(request.method, ruta, cuerpo, request.headers)
        except ErrorDeSeguridad as exc:
            return JSONResponse(status_code=exc.codigo,
                                content={"detail": exc.motivo, "seguridad": "RECHAZADA"})
        return await call_next(request)

    return True
