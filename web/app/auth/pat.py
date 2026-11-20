from fastapi import HTTPException

from app.auth.crypto import decrypt_token
from app.config import get_fernet
from app.models.user import User


def decrypt_pat(user: User) -> str:
    if not user.pat_encrypted:
        raise HTTPException(
            409,
            detail={
                "stage": "identity",
                "message": "Register a Forgejo PAT in Settings first.",
            },
        )
    try:
        return decrypt_token(get_fernet(), user.pat_encrypted)
    except ValueError:
        raise HTTPException(
            503,
            detail={
                "stage": "identity",
                "message": "Cannot decrypt the PAT. Check encryption settings and register it again.",
            },
        ) from None
