"""
Módulo Central de Algoritmos Criptográficos para los 14 Bancos.
Contiene las funciones para cifrar y descifrar según el algoritmo del banco.
"""

def caesar_cipher(text: str, shift: int = 3) -> str:
    result = []
    for char in text:
        if char.isalpha():
            start = ord('A') if char.isupper() else ord('a')
            result.append(chr((ord(char) - start + shift) % 26 + start))
        else:
            result.append(char)
    return "".join(result)

def caesar_decipher(text: str, shift: int = 3) -> str:
    return caesar_cipher(text, -shift)

def atbash_cipher(text: str) -> str:
    result = []
    for char in text:
        if char.isupper():
            result.append(chr(ord('Z') - (ord(char) - ord('A'))))
        elif char.islower():
            result.append(chr(ord('z') - (ord(char) - ord('a'))))
        else:
            result.append(char)
    return "".join(result)

# Stubs para el resto de los 14 algoritmos:
# Vigenère, Playfair, Hill, DES, 3DES, Blowfish, Twofish, AES, RSA, ElGamal, ECC, ChaCha20
