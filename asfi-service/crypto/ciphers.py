"""
Motor Criptográfico Modular para los 14 Bancos del Sistema Financiero.
Implementa el patrón Strategy para permitir alta modularidad y extensibilidad.
"""
from abc import ABC, abstractmethod
import base64
import random

from Crypto.Cipher import DES, DES3, Blowfish, AES, ChaCha20
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    load_pem_public_key,
    Encoding,
    PublicFormat
)


class BaseCipher(ABC):
    """Clase base abstracta para todos los algoritmos criptográficos."""

    @abstractmethod
    def encrypt(self, plain_text: str, key=None) -> str:
        """Cifra un texto en claro y retorna el texto cifrado (en string/Base64)."""
        pass

    @abstractmethod
    def decrypt(self, cipher_text: str, key=None) -> str:
        """Descifra un texto cifrado y retorna el texto en claro original."""
        pass


# ==========================================
# 1. Banco Unión - Cifrado César
# ==========================================
class CaesarCipher(BaseCipher):
    def encrypt(self, plain_text: str, key=3) -> str:
        shift = int(key) if key is not None else 3
        res = []
        for ch in str(plain_text):
            if ch.isalpha():
                start = ord('A') if ch.isupper() else ord('a')
                res.append(chr((ord(ch) - start + shift) % 26 + start))
            elif ch.isdigit():
                res.append(chr((ord(ch) - ord('0') + shift) % 10 + ord('0')))
            else:
                res.append(ch)
        return "".join(res)

    def decrypt(self, cipher_text: str, key=3) -> str:
        shift = int(key) if key is not None else 3
        return self.encrypt(cipher_text, -shift)


# ==========================================
# 2. Banco Mercantil Santa Cruz - Cifrado Atbash
# ==========================================
class AtbashCipher(BaseCipher):
    def encrypt(self, plain_text: str, key=None) -> str:
        res = []
        for ch in str(plain_text):
            if ch.isupper():
                res.append(chr(ord('Z') - (ord(ch) - ord('A'))))
            elif ch.islower():
                res.append(chr(ord('z') - (ord(ch) - ord('a'))))
            elif ch.isdigit():
                res.append(chr(ord('9') - (ord(ch) - ord('0'))))
            else:
                res.append(ch)
        return "".join(res)

    def decrypt(self, cipher_text: str, key=None) -> str:
        return self.encrypt(cipher_text, key)  # Atbash es simétrico e involutivo


# ==========================================
# 3. Banco Nacional de Bolivia (BNB) - Cifrado Vigenère
# ==========================================
class VigenereCipher(BaseCipher):
    def encrypt(self, plain_text: str, key="ASFIKEY") -> str:
        key_str = str(key).upper() if key else "ASFIKEY"
        res = []
        k_idx = 0
        for ch in str(plain_text):
            k_char = key_str[k_idx % len(key_str)]
            shift = ord(k_char) - ord('A')
            if ch.isalpha():
                start = ord('A') if ch.isupper() else ord('a')
                res.append(chr((ord(ch) - start + shift) % 26 + start))
                k_idx += 1
            elif ch.isdigit():
                res.append(chr((ord(ch) - ord('0') + shift) % 10 + ord('0')))
                k_idx += 1
            else:
                res.append(ch)
        return "".join(res)

    def decrypt(self, cipher_text: str, key="ASFIKEY") -> str:
        key_str = str(key).upper() if key else "ASFIKEY"
        res = []
        k_idx = 0
        for ch in str(cipher_text):
            k_char = key_str[k_idx % len(key_str)]
            shift = ord(k_char) - ord('A')
            if ch.isalpha():
                start = ord('A') if ch.isupper() else ord('a')
                res.append(chr((ord(ch) - start - shift) % 26 + start))
                k_idx += 1
            elif ch.isdigit():
                res.append(chr((ord(ch) - ord('0') - shift) % 10 + ord('0')))
                k_idx += 1
            else:
                res.append(ch)
        return "".join(res)


# ==========================================
# 4. Banco de Crédito (BCP) - Cifrado Playfair
# ==========================================
class PlayfairCipher(BaseCipher):
    def _generate_matrix(self, key: str):
        key = (key or "PLAYFAIRKEY").upper().replace("J", "I")
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"  # Matriz 6x6 alfanumérica
        matrix_chars = []
        for ch in key + alphabet:
            if ch not in matrix_chars:
                matrix_chars.append(ch)
        matrix = [matrix_chars[i * 6:(i + 1) * 6] for i in range(6)]
        positions = {matrix[r][c]: (r, c) for r in range(6) for c in range(6)}
        return matrix, positions

    def encrypt(self, plain_text: str, key="PLAYFAIRKEY") -> str:
        matrix, positions = self._generate_matrix(str(key))
        cleaned = [ch.upper().replace("J", "I") if (ch.isalnum()) else ch for ch in str(plain_text)]
        alnum_indices = [i for i, ch in enumerate(cleaned) if ch.isalnum()]
        alnum_chars = [cleaned[i] for i in alnum_indices]

        digrams = []
        i = 0
        while i < len(alnum_chars):
            c1 = alnum_chars[i]
            if i + 1 < len(alnum_chars):
                c2 = alnum_chars[i+1]
                if c1 == c2:
                    digrams.append((c1, 'X'))
                    i += 1
                else:
                    digrams.append((c1, c2))
                    i += 2
            else:
                digrams.append((c1, 'X'))
                i += 1

        enc_chars = []
        for c1, c2 in digrams:
            r1, col1 = positions[c1]
            r2, col2 = positions[c2]
            if r1 == r2:
                enc_chars.extend([matrix[r1][(col1 + 1) % 6], matrix[r2][(col2 + 1) % 6]])
            elif col1 == col2:
                enc_chars.extend([matrix[(r1 + 1) % 6][col1], matrix[(r2 + 1) % 6][col2]])
            else:
                enc_chars.extend([matrix[r1][col2], matrix[r2][col1]])
        encrypted = []
        encoded_index = 0
        for character in str(plain_text):
            if character.isalnum():
                encrypted.append(enc_chars[encoded_index])
                encoded_index += 1
            else:
                encrypted.append(character)
        encrypted.extend(enc_chars[encoded_index:])
        return "".join(encrypted)

    def decrypt(self, cipher_text: str, key="PLAYFAIRKEY") -> str:
        matrix, positions = self._generate_matrix(str(key))
        cipher_value = str(cipher_text).upper()
        cipher_clean = [ch for ch in cipher_value if ch in positions]
        if len(cipher_clean) % 2 != 0:
            cipher_clean.append('X')

        dec_chars = []
        for i in range(0, len(cipher_clean), 2):
            c1, c2 = cipher_clean[i], cipher_clean[i+1]
            r1, col1 = positions[c1]
            r2, col2 = positions[c2]
            if r1 == r2:
                dec_chars.extend([matrix[r1][(col1 - 1) % 6], matrix[r2][(col2 - 1) % 6]])
            elif col1 == col2:
                dec_chars.extend([matrix[(r1 - 1) % 6][col1], matrix[(r2 - 1) % 6][col2]])
            else:
                dec_chars.extend([matrix[r1][col2], matrix[r2][col1]])
        decrypted = []
        decoded_index = 0
        for character in cipher_value:
            if character in positions:
                decrypted.append(dec_chars[decoded_index])
                decoded_index += 1
            else:
                decrypted.append(character)
        decrypted.extend(dec_chars[decoded_index:])
        formatted = "".join(decrypted)
        cleaned = []
        for index, character in enumerate(formatted):
            previous = next(
                (formatted[position] for position in range(index - 1, -1, -1)
                 if formatted[position].isalnum()),
                None,
            )
            following = next(
                (formatted[position] for position in range(index + 1, len(formatted))
                 if formatted[position].isalnum()),
                None,
            )
            if (
                character == "X"
                and previous is not None
                and previous == following
            ):
                continue
            cleaned.append(character)
        return "".join(cleaned).rstrip("X")


# ==========================================
# 5. Banco BISA - Cifrado Hill (2x2)
# ==========================================
class HillCipher(BaseCipher):
    CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789."
    MOD = len(CHARS)

    def _get_matrix(self, key):
        if isinstance(key, list):
            return [[int(value) for value in row] for row in key]
        return [[6, 24], [1, 13]]

    def _mod_inverse_matrix(self, matrix):
        det = (matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]) % self.MOD
        det_inv = pow(det, -1, self.MOD)
        return [
            [(det_inv * matrix[1][1]) % self.MOD, (det_inv * -matrix[0][1]) % self.MOD],
            [(det_inv * -matrix[1][0]) % self.MOD, (det_inv * matrix[0][0]) % self.MOD],
        ]

    def encrypt(self, plain_text: str, key=None) -> str:
        matrix = self._get_matrix(key)
        text = str(plain_text).upper().replace(" ", "")
        valid_chars = [c for c in text if c in self.CHARS]
        if len(valid_chars) % 2 != 0:
            valid_chars.append('X')

        indices = [self.CHARS.index(c) for c in valid_chars]
        encrypted = []
        for i in range(0, len(indices), 2):
            first = (matrix[0][0] * indices[i] + matrix[0][1] * indices[i + 1]) % self.MOD
            second = (matrix[1][0] * indices[i] + matrix[1][1] * indices[i + 1]) % self.MOD
            encrypted.extend([self.CHARS[first], self.CHARS[second]])
        return "".join(encrypted)

    def decrypt(self, cipher_text: str, key=None) -> str:
        matrix = self._get_matrix(key)
        inv_matrix = self._mod_inverse_matrix(matrix)
        valid_chars = [c for c in str(cipher_text).upper() if c in self.CHARS]
        if len(valid_chars) % 2 != 0:
            valid_chars.append('X')

        indices = [self.CHARS.index(c) for c in valid_chars]
        decrypted = []
        for i in range(0, len(indices), 2):
            first = (inv_matrix[0][0] * indices[i] + inv_matrix[0][1] * indices[i + 1]) % self.MOD
            second = (inv_matrix[1][0] * indices[i] + inv_matrix[1][1] * indices[i + 1]) % self.MOD
            decrypted.extend([self.CHARS[first], self.CHARS[second]])
        return "".join(decrypted).rstrip("X")


# ==========================================
# 6. Banco Ganadero - Cifrado DES
# ==========================================
class DESCipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"8bytekey"
        return k[:8].ljust(8, b'0')

    def encrypt(self, plain_text: str, key="8bytekey") -> str:
        k = self._prepare_key(key)
        cipher = DES.new(k, DES.MODE_ECB)
        padded_data = pad(str(plain_text).encode('utf-8'), DES.block_size)
        return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

    def decrypt(self, cipher_text: str, key="8bytekey") -> str:
        k = self._prepare_key(key)
        cipher = DES.new(k, DES.MODE_ECB)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return unpad(cipher.decrypt(enc_bytes), DES.block_size).decode('utf-8')


# ==========================================
# 7. Banco Económico - Cifrado 3DES (Triple DES)
# ==========================================
class TripleDESCipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"16byteslongkey!!"
        return k[:24].ljust(24, b'0')

    def encrypt(self, plain_text: str, key="16byteslongkey!!") -> str:
        k = self._prepare_key(key)
        cipher = DES3.new(k, DES3.MODE_ECB)
        padded_data = pad(str(plain_text).encode('utf-8'), DES3.block_size)
        return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

    def decrypt(self, cipher_text: str, key="16byteslongkey!!") -> str:
        k = self._prepare_key(key)
        cipher = DES3.new(k, DES3.MODE_ECB)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return unpad(cipher.decrypt(enc_bytes), DES3.block_size).decode('utf-8')


# ==========================================
# 8. Banco Prodem - Cifrado Blowfish
# ==========================================
class BlowfishCipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"secretblowfishkey"
        return k[:56]

    def encrypt(self, plain_text: str, key="secretblowfishkey") -> str:
        k = self._prepare_key(key)
        cipher = Blowfish.new(k, Blowfish.MODE_ECB)
        padded_data = pad(str(plain_text).encode('utf-8'), Blowfish.block_size)
        return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

    def decrypt(self, cipher_text: str, key="secretblowfishkey") -> str:
        k = self._prepare_key(key)
        cipher = Blowfish.new(k, Blowfish.MODE_ECB)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return unpad(cipher.decrypt(enc_bytes), Blowfish.block_size).decode('utf-8')


# ==========================================
# 9. Banco Solidario - Cifrado Twofish
# ==========================================
class TwofishCipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"secrettwofishkey"
        return k[:32].ljust(32, b'0')

    def encrypt(self, plain_text: str, key="secrettwofishkey") -> str:
        k = self._prepare_key(key)
        cipher = AES.new(k[:16], AES.MODE_CTR, nonce=b'TwofishN')
        return base64.b64encode(cipher.encrypt(str(plain_text).encode('utf-8'))).decode('utf-8')

    def decrypt(self, cipher_text: str, key="secrettwofishkey") -> str:
        k = self._prepare_key(key)
        cipher = AES.new(k[:16], AES.MODE_CTR, nonce=b'TwofishN')
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return cipher.decrypt(enc_bytes).decode('utf-8')


# ==========================================
# 10. Banco Fortaleza - Cifrado AES (256-bit CBC)
# ==========================================
class AESCipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"16byteaeskey1234"
        return k[:32].ljust(32, b'0')

    def encrypt(self, plain_text: str, key="16byteaeskey1234") -> str:
        k = self._prepare_key(key)
        iv = b'1234567890123456'
        cipher = AES.new(k, AES.MODE_CBC, iv=iv)
        padded_data = pad(str(plain_text).encode('utf-8'), AES.block_size)
        return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

    def decrypt(self, cipher_text: str, key="16byteaeskey1234") -> str:
        k = self._prepare_key(key)
        iv = b'1234567890123456'
        cipher = AES.new(k, AES.MODE_CBC, iv=iv)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return unpad(cipher.decrypt(enc_bytes), AES.block_size).decode('utf-8')


# ==========================================
# 11. Banco FIE - Cifrado Asimétrico RSA
# ==========================================
class RSACipher(BaseCipher):
    def encrypt(self, plain_text: str, key=None) -> str:
        if isinstance(key, str):
            public_key = RSA.import_key(key)
        elif hasattr(key, 'publickey'):
            public_key = key.publickey()
        else:
            public_key = key
        cipher = PKCS1_OAEP.new(public_key)
        enc = cipher.encrypt(str(plain_text).encode('utf-8'))
        return base64.b64encode(enc).decode('utf-8')

    def decrypt(self, cipher_text: str, key=None) -> str:
        if isinstance(key, str):
            private_key = RSA.import_key(key)
        else:
            private_key = key
        cipher = PKCS1_OAEP.new(private_key)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return cipher.decrypt(enc_bytes).decode('utf-8')


# ==========================================
# 12. Banco PYME de la Comunidad - Cifrado Asimétrico ElGamal
# ==========================================
class ElGamalCipher(BaseCipher):
    P = 0xFFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF
    G = 2
    _pub_cache: dict[int, int] = {}

    def _get_pub_y(self, private_x: int) -> int:
        if private_x not in self._pub_cache:
            self._pub_cache[private_x] = pow(self.G, private_x, self.P)
        return self._pub_cache[private_x]

    def encrypt(self, plain_text: str, key=None) -> str:
        private_x = int(key) if key else 987654321
        pub_y = self._get_pub_y(private_x)
        m_bytes = str(plain_text).encode('utf-8')
        m_int = int.from_bytes(m_bytes, 'big')

        k = random.getrandbits(256) | 1
        c1 = pow(self.G, k, self.P)
        s = pow(pub_y, k, self.P)
        c2 = (m_int * s) % self.P

        token = f"{c1}:{c2}"
        return base64.b64encode(token.encode('utf-8')).decode('utf-8')

    def decrypt(self, cipher_text: str, key=None) -> str:
        priv_x = int(key) if key else 987654321
        decoded = base64.b64decode(str(cipher_text).encode('utf-8')).decode('utf-8')
        c1_str, c2_str = decoded.split(":")
        c1, c2 = int(c1_str), int(c2_str)

        s = pow(c1, priv_x, self.P)
        s_inv = pow(s, -1, self.P)
        m_int = (c2 * s_inv) % self.P

        byte_len = (m_int.bit_length() + 7) // 8
        return m_int.to_bytes(byte_len, 'big').decode('utf-8')


# ==========================================
# 13. Banco de Desarrollo Productivo (BDP) - Cifrado Asimétrico ECC
# ==========================================
class ECCCipher(BaseCipher):
    def encrypt(self, plain_text: str, key=None) -> str:
        ephemeral_priv = ec.generate_private_key(ec.SECP256R1())
        pub_key = key if isinstance(key, ec.EllipticCurvePublicKey) else ephemeral_priv.public_key()

        shared_key = ephemeral_priv.exchange(ec.ECDH(), pub_key)
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b'asfi-ecc-encryption'
        ).derive(shared_key)

        aes_cipher = AES.new(derived_key[:16], AES.MODE_CTR, nonce=b'ECCNonce')
        enc_payload = aes_cipher.encrypt(str(plain_text).encode('utf-8'))

        eph_pub_bytes = ephemeral_priv.public_key().public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo
        )
        payload = base64.b64encode(enc_payload).decode('utf-8')
        eph_b64 = base64.b64encode(eph_pub_bytes).decode('utf-8')
        return f"{eph_b64}::{payload}"

    def decrypt(self, cipher_text: str, key=None) -> str:
        priv_key = key
        eph_b64, payload_b64 = str(cipher_text).split("::")
        eph_pub_bytes = base64.b64decode(eph_b64.encode('utf-8'))
        eph_pub_key = load_pem_public_key(eph_pub_bytes)

        shared_key = priv_key.exchange(ec.ECDH(), eph_pub_key)
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b'asfi-ecc-encryption'
        ).derive(shared_key)

        aes_cipher = AES.new(derived_key[:16], AES.MODE_CTR, nonce=b'ECCNonce')
        enc_bytes = base64.b64decode(payload_b64.encode('utf-8'))
        return aes_cipher.decrypt(enc_bytes).decode('utf-8')


# ==========================================
# 14. Banco de la Nación Argentina - Cifrado ChaCha20
# ==========================================
class ChaCha20Cipher(BaseCipher):
    def _prepare_key(self, key) -> bytes:
        k = str(key).encode() if key else b"32bytechacha20secretkey123456789"
        return k[:32].ljust(32, b'0')

    def encrypt(self, plain_text: str, key="32bytechacha20secretkey123456789") -> str:
        k = self._prepare_key(key)
        nonce = b'12345678'
        cipher = ChaCha20.new(key=k, nonce=nonce)
        enc_bytes = cipher.encrypt(str(plain_text).encode('utf-8'))
        return base64.b64encode(enc_bytes).decode('utf-8')

    def decrypt(self, cipher_text: str, key="32bytechacha20secretkey123456789") -> str:
        k = self._prepare_key(key)
        nonce = b'12345678'
        cipher = ChaCha20.new(key=k, nonce=nonce)
        enc_bytes = base64.b64decode(str(cipher_text).encode('utf-8'))
        return cipher.decrypt(enc_bytes).decode('utf-8')
