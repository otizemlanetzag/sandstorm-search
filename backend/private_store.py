from __future__ import annotations

"""Opaque encrypted blob storage.

The server intentionally treats payloads as bytes. It does not receive or
handle the user's encryption key and cannot search the plaintext. A real
client encrypts locally with backend/e2e_crypto.py and uploads only ciphertext.
"""

import hashlib
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "private.db"

router = APIRouter(prefix="/api/private", tags=["private"])


class EncryptedBlob(BaseModel):
    blob: str = Field(min_length=1, max_length=20_000_000)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS blobs ("
        "id TEXT PRIMARY KEY, blob TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return conn


def blob_id(blob: str) -> str:
    # Content addressing avoids storing plaintext-derived metadata.
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


@router.post("/blobs")
def put_blob(payload: EncryptedBlob):
    try:
        payload.blob.encode("ascii")
    except UnicodeEncodeError:
        raise HTTPException(status_code=400, detail="Ciphertext must be ASCII base64url")
    ident = blob_id(payload.blob)
    conn = db()
    try:
        conn.execute("INSERT OR IGNORE INTO blobs(id, blob) VALUES(?, ?)", (ident, payload.blob))
        conn.commit()
    finally:
        conn.close()
    return {"id": ident}


@router.get("/blobs/{ident}")
def get_blob(ident: str):
    if len(ident) != 64 or any(c not in "0123456789abcdef" for c in ident):
        raise HTTPException(status_code=400, detail="Invalid blob id")
    conn = db()
    try:
        row = conn.execute("SELECT blob FROM blobs WHERE id=?", (ident,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Blob not found")
    return {"id": ident, "blob": row[0]}
