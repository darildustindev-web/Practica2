# pyrefly: ignore [missing-import]
from fastapi import FastAPI
import secrets

app = FastAPI(title="Servicio Central ASFI", version="1.0.0")


def generate_verification_code() -> str:
    """Genera un código de verificación de 8 caracteres hexadecimales (0-9, A-F)."""
    return secrets.token_hex(4).upper()

@app.get("/")
def read_root():
    return {"message": "Servicio Central ASFI Operativo"}

@app.post("/api/asfi/ejecutar-conversion")
async def ejecutar_barrido_conversion():
    """
    Realiza el barrido paralelo asíncrono consultando el tipo de cambio del BCB
    y consumiendo las APIs de los 14 bancos de forma simultánea.
    """
    verification_code = generate_verification_code()
    # Stub de orquestación asíncrona
    return {
        "status": "PROCESADO",
        "mensaje": "Barrido paralelo completado exitosamente",
        "codigo_verificacion_demo": verification_code
    }
