"""
Gestor de Llaves Criptográficas de la ASFI para las 14 entidades financieras.
"""

BANK_KEYS = {
    1: {"name": "Banco Unión S.A.", "cipher": "César", "key": 3},
    2: {"name": "Banco Mercantil Santa Cruz S.A.", "cipher": "Atbash", "key": None},
    3: {"name": "Banco Nacional de Bolivia S.A.", "cipher": "Vigenère", "key": "ASFIKEY"},
    4: {"name": "Banco de Crédito de Bolivia S.A.", "cipher": "Playfair", "key": "PLAYFAIRKEY"},
    5: {"name": "Banco BISA S.A.", "cipher": "Hill", "key": [[6, 24], [1, 13]]},
    6: {"name": "Banco Ganadero S.A.", "cipher": "DES", "key": "8bytekey"},
    7: {"name": "Banco Económico S.A.", "cipher": "3DES", "key": "16byteslongkey!!"},
    8: {"name": "Banco Prodem S.A.", "cipher": "Blowfish", "key": "secretblowfishkey"},
    9: {"name": "Banco Solidario S.A.", "cipher": "Twofish", "key": "secrettwofishkey"},
    10: {"name": "Banco Fortaleza S.A.", "cipher": "AES", "key": "16byteaeskey1234"},
    11: {"name": "Banco FIE S.A.", "cipher": "RSA", "key": "rsa_keys"},
    12: {"name": "Banco PYME de la Comunidad S.A.", "cipher": "ElGamal", "key": "elgamal_keys"},
    13: {"name": "Banco de Desarrollo Productivo S.A.M.", "cipher": "ECC", "key": "ecc_keys"},
    14: {"name": "Banco de la Nación Argentina", "cipher": "ChaCha20", "key": "32bytechacha20secretkey123456789"},
}

def get_bank_key(banco_id: int):
    return BANK_KEYS.get(banco_id)
