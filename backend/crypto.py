from __future__ import annotations

"""Application-level authenticated encryption helpers.

The key is supplied through SANDSTORM_ENCRYPTION_KEY and is never stored in
this repository. This module is intended for encrypting sensitive local
metadata/configuration, not for making the public search index searchable
without revealing plaintext to the server.
"""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken


ENV_KEY = "SANDSTORM_ENCRYPTION_KEY"


def get_cipher() -> Fernet:
    value = os.getenv(ENV_KEY)
    if not value:
        raise RuntimeError(
            f"{ENV_KEY} is not set. Generate a Fernet key and keep it outside the repository."
        )
    try:
        return Fernet(value.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("Invalid Fernet key in SANDSTORM_ENCRYPTION_KEY") from exc


def encrypt_text(value: str) -> str:
    token = get_cipher().encrypt(value.encode("utf-8"))
    return base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_text(value: str) -> str:
    try:
        token = base64.urlsafe_b64decode(value.encode("ascii"))
        return get_cipher().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Encrypted value could not be authenticated/decrypted") from exc
