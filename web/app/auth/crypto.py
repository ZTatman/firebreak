"""Fernet (AES) encryption for OAuth tokens at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


def fernet_from_encryption_key(key: SecretStr) -> Fernet | None:
    raw = key.get_secret_value().strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode())
    except Exception as e:
        msg = (
            f"Invalid TOKEN_ENCRYPTION_KEY: {e}. "
            "Generate a valid key with: uv run python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
        raise ValueError(msg) from e


def encrypt_token(fernet: Fernet, raw_token: str) -> str:
    return fernet.encrypt(raw_token.encode()).decode()


def encrypt_optional(fernet: Fernet | None, raw_token: str | None) -> str | None:
    if raw_token is None:
        return None
    if fernet is None:
        msg = "Token encryption is not configured. Set TOKEN_ENCRYPTION_KEY in your .env file or deployment environment."
        raise ValueError(msg)
    return encrypt_token(fernet, raw_token)


def decrypt_token(fernet: Fernet, encrypted_token: str) -> str:
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Cannot decrypt stored token — the encryption key may have changed or the "
            "token data is corrupted. The user may need to re-connect their account."
        ) from None


def decrypt_optional(fernet: Fernet | None, encrypted_token: str | None) -> str | None:
    if encrypted_token is None:
        return None
    if fernet is None:
        msg = "Token encryption is not configured. Set TOKEN_ENCRYPTION_KEY in your .env file or deployment environment."
        raise ValueError(msg)
    return decrypt_token(fernet, encrypted_token)
