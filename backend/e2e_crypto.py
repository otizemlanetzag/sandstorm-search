from __future__ import annotations

"""Client-side encryption primitives for Sandstorm.

This module deliberately does not contact the server. A browser/client can
use the same protocol: generate a random key locally, encrypt the payload,
and only send ciphertext to the server. The server must never receive the
key.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12
KEY_SIZE = 32


def generate_key() -> str:
    """Create a 256-bit AES-GCM key encoded for local storage."""
    return base64.urlsafe_b64encode(os.urandom(KEY_SIZE)).decode("ascii")


def encrypt(key_b64: str, plaintext: str, aad: bytes | None = None) -> str:
    key = base64.urlsafe_b64decode(key_b64.encode("ascii"))
    if len(key) != KEY_SIZE:
        raise ValueError("Key must be 256 bits")
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt(key_b64: str, token_b64: str, aad: bytes | None = None) -> str:
    key = base64.urlsafe_b64decode(key_b64.encode("ascii"))
    token = base64.urlsafe_b64decode(token_b64.encode("ascii"))
    if len(key) != KEY_SIZE or len(token) <= NONCE_SIZE:
        raise ValueError("Invalid encrypted payload")
    nonce, ciphertext = token[:NONCE_SIZE], token[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
