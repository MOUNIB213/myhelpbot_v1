import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _HAS_ARGON2 = True
    _ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
except ImportError:
    _HAS_ARGON2 = False

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False

try:
    import jwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False


class PasswordManager:
    """Argon2id Password Hasher with PBKDF2-HMAC-SHA256 fallback for restricted environments."""

    @staticmethod
    def hash_password(password: str) -> str:
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if _HAS_ARGON2:
            return _ph.hash(password)
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310000)
        return f"pbkdf2_sha256$310000${salt}${dk.hex()}"

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        if not password or not hashed:
            return False
        if hashed.startswith("pbkdf2_sha256$"):
            parts = hashed.split("$")
            if len(parts) != 4:
                return False
            iterations = int(parts[1])
            salt = parts[2]
            expected_hex = parts[3]
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
            return hmac.compare_digest(dk.hex(), expected_hex)
        if _HAS_ARGON2:
            try:
                return _ph.verify(hashed, password)
            except VerifyMismatchError:
                return False
        return False


class SecretVaultCipher:
    """Encrypts and decrypts dynamic secrets (such as Gemini API keys) in PostgreSQL."""

    def __init__(self, master_key: str):
        raw_bytes = hashlib.sha256(master_key.encode("utf-8")).digest()
        self._fernet_key = base64.urlsafe_b64encode(raw_bytes)
        self._raw_key = raw_bytes
        if _HAS_FERNET:
            self._fernet = Fernet(self._fernet_key)
        else:
            self._fernet = None

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        if self._fernet:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        # Authenticated XOR-HMAC stream cipher fallback if cryptography C-ext unavailable
        nonce = secrets.token_bytes(16)
        pt_bytes = plaintext.encode("utf-8")
        keystream = self._derive_keystream(nonce, len(pt_bytes))
        ct = bytes(a ^ b for a, b in zip(pt_bytes, keystream))
        mac = hmac.new(self._raw_key, nonce + ct, hashlib.sha256).digest()
        return "v1:" + base64.urlsafe_b64encode(nonce + mac + ct).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        if ciphertext.startswith("v1:"):
            raw = base64.urlsafe_b64decode(ciphertext[3:].encode("utf-8"))
            nonce, mac, ct = raw[:16], raw[16:48], raw[48:]
            expected_mac = hmac.new(self._raw_key, nonce + ct, hashlib.sha256).digest()
            if not hmac.compare_digest(mac, expected_mac):
                raise ValueError("Secret integrity check failed (HMAC mismatch).")
            keystream = self._derive_keystream(nonce, len(ct))
            return bytes(a ^ b for a, b in zip(ct, keystream)).decode("utf-8")
        if self._fernet:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        raise RuntimeError("Fernet library required to decrypt non-v1 token.")

    def _derive_keystream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hashlib.sha256(self._raw_key + nonce + counter.to_bytes(4, "big")).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    @staticmethod
    def mask_secret(secret: str) -> str:
        if not secret or len(secret) < 8:
            return "••••••••"
        return f"{secret[:4]}••••••••••••{secret[-4:]}"


class JWTManager:
    """HS256 JSON Web Token generator and verifier with session revocation support."""

    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_token(
        self,
        subject: str,
        role: str,
        session_jti: str,
        expires_delta: timedelta,
        token_type: str = "access",
    ) -> str:
        now = datetime.now(timezone.utc)
        exp = now + expires_delta
        payload = {
            "sub": str(subject),
            "role": role,
            "jti": session_jti,
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "csrf": secrets.token_urlsafe(16),
        }
        if _HAS_PYJWT:
            return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return self._encode_hs256(payload)

    def decode_token(self, token: str) -> Dict[str, Any]:
        if _HAS_PYJWT:
            return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        return self._decode_hs256(token)

    def _encode_hs256(self, payload: Dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        h_b64 = base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode()).rstrip(b"=")
        p_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
        signing_input = h_b64 + b"." + p_b64
        sig = hmac.new(self.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        s_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
        return (signing_input + b"." + s_b64).decode("utf-8")

    def _decode_hs256(self, token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT structure.")
        signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
        expected_sig = hmac.new(self.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        rem = len(parts[2]) % 4
        padded_sig = parts[2] + ("=" * (4 - rem) if rem else "")
        actual_sig = base64.urlsafe_b64decode(padded_sig.encode("utf-8"))
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Invalid JWT signature.")
        rem_p = len(parts[1]) % 4
        padded_p = parts[1] + ("=" * (4 - rem_p) if rem_p else "")
        payload = json.loads(base64.urlsafe_b64decode(padded_p.encode("utf-8")).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("Token has expired.")
        return payload


REQUIRED_UNAUTHORIZED_MESSAGE = (
    "هذا البوت خاص ولا تملك صلاحية استخدامه. يرجى التواصل مع مالك البوت للحصول على إمكانية الوصول."
)

DEFAULT_ALLOWED_SECTIONS = [
    "ai", "projects", "links", "notes", "tasks",
    "reminders", "favorites", "search", "account", "settings"
]


def verify_backup_file_integrity(file_path: str, expected_sha256: str) -> bool:
    from pathlib import Path
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return False
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != expected_sha256:
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return "version" in data and "projects" in data and "links" in data
    except Exception:
        return False
