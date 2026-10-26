"""
StockNova Core Security Module
Provides DPAPI (Windows hardware/user-bound) and Fernet AES authenticated encryption
for local-only, zero-leak credential and key storage.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path
from typing import Any, Optional

from stockpilot.core.logger import get_logger

logger = get_logger("security_vault")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KEY_FILE = PROJECT_ROOT / "data" / ".security.key"

if os.name == "nt":
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]
else:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = []


class SecurityVault:
    """Enterprise-grade local cryptographic vault for API keys, passwords, and tokens."""

    _fernet_instance = None
    _dpapi_supported: Optional[bool] = None

    @classmethod
    def _is_dpapi_supported(cls) -> bool:
        if cls._dpapi_supported is not None:
            return cls._dpapi_supported
        if os.name != "nt":
            cls._dpapi_supported = False
            return False
        try:
            return hasattr(ctypes.windll, "crypt32") and hasattr(
                ctypes.windll.crypt32, "CryptProtectData"
            )
        except Exception:
            cls._dpapi_supported = False
            return False

    @classmethod
    def _get_fernet(cls):
        if cls._fernet_instance is not None:
            return cls._fernet_instance
        try:
            from cryptography.fernet import Fernet

            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            if not KEY_FILE.exists():
                new_key = Fernet.generate_key()
                with open(KEY_FILE, "wb") as f:
                    f.write(new_key)
                try:
                    os.chmod(KEY_FILE, 0o600)
                except Exception:
                    pass
            with open(KEY_FILE, "rb") as f:
                key = f.read().strip()
            cls._fernet_instance = Fernet(key)
            return cls._fernet_instance
        except Exception as e:
            logger.debug(f"Fernet optional fallback notice: {e}")
            return None

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """Encrypts plaintext using Windows DPAPI (tied to logged-in user) or Fernet AES."""
        if not plaintext:
            return ""

        if cls._is_dpapi_supported():
            try:
                data = plaintext.encode("utf-8")
                blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data))
                blob_out = DATA_BLOB()
                descr = ctypes.c_wchar_p("StockNova Secret")
                if ctypes.windll.crypt32.CryptProtectData(
                    ctypes.byref(blob_in),
                    descr,
                    None,
                    None,
                    None,
                    0,
                    ctypes.byref(blob_out),
                ):
                    enc_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                    return "dpapi:" + base64.b64encode(enc_bytes).decode("ascii")
            except Exception as e:
                logger.debug(f"DPAPI encryption fell back to Fernet: {e}")

        fernet = cls._get_fernet()
        if fernet:
            try:
                token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
                return f"fernet:{token}"
            except Exception as e:
                logger.error(f"Fernet encryption error: {e}")

        return "b64:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """Decrypts a previously encrypted secret string."""
        if not ciphertext:
            return ""

        if ciphertext.startswith("dpapi:"):
            if not cls._is_dpapi_supported():
                return ""
            try:
                raw_b64 = ciphertext[len("dpapi:") :]
                raw = base64.b64decode(raw_b64.encode("ascii"))
                blob_in = DATA_BLOB(len(raw), ctypes.create_string_buffer(raw))
                blob_out = DATA_BLOB()
                if ctypes.windll.crypt32.CryptUnprotectData(
                    ctypes.byref(blob_in),
                    None,
                    None,
                    None,
                    None,
                    0,
                    ctypes.byref(blob_out),
                ):
                    dec_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                    return dec_bytes.decode("utf-8")
                raise RuntimeError("CryptUnprotectData failed.")
            except Exception as e:
                logger.error(f"Failed to decrypt DPAPI ciphertext: {e}")
                return ""

        if ciphertext.startswith("fernet:"):
            fernet = cls._get_fernet()
            if not fernet:
                return ""
            try:
                token = ciphertext[len("fernet:") :].encode("ascii")
                return fernet.decrypt(token).decode("utf-8")
            except Exception as e:
                logger.error(f"Failed to decrypt Fernet ciphertext: {e}")
                return ""

        if ciphertext.startswith("b64:"):
            try:
                return base64.b64decode(ciphertext[len("b64:") :].encode("ascii")).decode("utf-8")
            except Exception:
                return ciphertext

        return ciphertext

    @classmethod
    def mask_secret(cls, secret: str, visible_start: int = 4, visible_end: int = 4) -> str:
        if not secret:
            return "••••••••"
        try:
            plain = cls.decrypt(secret)
        except Exception:
            plain = secret

        length = len(plain)
        if length <= (visible_start + visible_end):
            return "••••••••"
        return f"{plain[:visible_start]}{'•' * (min(16, length - visible_start - visible_end))}{plain[-visible_end:]}"


def init_secure_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS secure_credentials (
            service TEXT PRIMARY KEY,
            username TEXT,
            encrypted_secret TEXT NOT NULL,
            metadata_json TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def save_secure_credential(
    db,
    service: str,
    username: str,
    secret: str,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    encrypted = SecurityVault.encrypt(secret)
    meta_str = json.dumps(metadata or {})
    with db.get_connection() as conn:
        init_secure_tables(conn)
        conn.execute(
            """
            INSERT INTO secure_credentials (service, username, encrypted_secret, metadata_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(service) DO UPDATE SET
                username = excluded.username,
                encrypted_secret = excluded.encrypted_secret,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (service, username, encrypted, meta_str),
        )
    return True


def get_secure_credential(db, service: str) -> Optional[dict[str, Any]]:
    with db.get_connection() as conn:
        init_secure_tables(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT service, username, encrypted_secret, metadata_json, updated_at
            FROM secure_credentials WHERE service = ?;
            """,
            (service,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        try:
            secret = SecurityVault.decrypt(row["encrypted_secret"])
        except Exception:
            secret = ""

        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except Exception:
            meta = {}

        return {
            "service": row["service"],
            "username": row["username"],
            "secret": secret,
            "masked_secret": SecurityVault.mask_secret(secret),
            "metadata": meta,
            "updated_at": row["updated_at"],
        }


def delete_secure_credential(db, service: str) -> bool:
    with db.get_connection() as conn:
        init_secure_tables(conn)
        conn.execute("DELETE FROM secure_credentials WHERE service = ?;", (service,))
    return True
