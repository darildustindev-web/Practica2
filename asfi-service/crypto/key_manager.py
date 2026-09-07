"""
Gestor de Llaves Criptográficas de la ASFI y Fábrica de Cifrados (CipherFactory).
Implementa el patrón Strategy/Factory para máxima modularidad y extensibilidad.
"""
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from Crypto.PublicKey import RSA
from .ciphers import (
    CaesarCipher,
    AtbashCipher,
    VigenereCipher,
    PlayfairCipher,
    HillCipher,
    DESCipher,
    TripleDESCipher,
    BlowfishCipher,
    TwofishCipher,
    AESCipher,
    RSACipher,
    ElGamalCipher,
    ECCCipher,
    ChaCha20Cipher,
)

BANK_CONFIG = {
    1: {"name": "Banco Unión S.A.", "type": "César", "key": 3, "cipher_cls": CaesarCipher},
    2: {"name": "Banco Mercantil Santa Cruz S.A.", "type": "Atbash", "key": None, "cipher_cls": AtbashCipher},
    3: {"name": "Banco Nacional de Bolivia S.A.", "type": "Vigenère", "key": "ASFIKEY", "cipher_cls": VigenereCipher},
    4: {"name": "Banco de Crédito de Bolivia S.A.", "type": "Playfair", "key": "PLAYFAIRKEY", "cipher_cls": PlayfairCipher},
    5: {"name": "Banco BISA S.A.", "type": "Hill", "key": [[6, 24], [1, 13]], "cipher_cls": HillCipher},
    6: {"name": "Banco Ganadero S.A.", "type": "DES", "key": "8bytekey", "cipher_cls": DESCipher},
    7: {"name": "Banco Económico S.A.", "type": "3DES", "key": "16byteslongkey!!", "cipher_cls": TripleDESCipher},
    8: {"name": "Banco Prodem S.A.", "type": "Blowfish", "key": "secretblowfishkey", "cipher_cls": BlowfishCipher},
    9: {"name": "Banco Solidario S.A.", "type": "Twofish", "key": "secrettwofishkey", "cipher_cls": TwofishCipher},
    10: {"name": "Banco Fortaleza S.A.", "type": "AES", "key": "16byteaeskey1234", "cipher_cls": AESCipher},
    11: {"name": "Banco FIE S.A.", "type": "RSA", "key": None, "cipher_cls": RSACipher},
    12: {"name": "Banco PYME de la Comunidad S.A.", "type": "ElGamal", "key": 987654321, "cipher_cls": ElGamalCipher},
    13: {"name": "Banco de Desarrollo Productivo S.A.M.", "type": "ECC", "key": None, "cipher_cls": ECCCipher},
    14: {"name": "Banco de la Nación Argentina", "type": "ChaCha20", "key": "32bytechacha20secretkey123456789", "cipher_cls": ChaCha20Cipher},
}


class CipherFactory:
    """Fábrica para instanciar y retornar el algoritmo de cifrado correspondiente a cada banco."""

    @staticmethod
    def get_cipher_for_bank(banco_id: int):
        config = BANK_CONFIG.get(banco_id)
        if not config:
            raise ValueError(f"Banco ID {banco_id} no registrado en el sistema ASFI.")

        cipher_instance = config["cipher_cls"]()
        key = config["key"]

        # Las claves asimétricas se mantienen estables durante el proceso.
        if banco_id == 11:
            key = _load_or_create_rsa_key()
        if banco_id == 13:  # ECC
            key = _load_or_create_ecc_key()

        return cipher_instance, key


def get_bank_key(banco_id: int):
    return BANK_CONFIG.get(banco_id)


KEY_DIR = Path(__file__).resolve().parents[2] / "data" / "keys"


def _load_or_create_rsa_key():
    path = KEY_DIR / "bank_11_rsa.pem"
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return RSA.import_key(path.read_bytes())
    key = RSA.generate(2048)
    path.write_bytes(key.export_key())
    return key


def _load_or_create_ecc_key():
    path = KEY_DIR / "bank_13_ecc.pem"
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key
