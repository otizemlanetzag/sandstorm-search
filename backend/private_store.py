from __future__ import annotations

"""Opaque encrypted blob storage for local development.

The local API mirrors the Netlify capability model: the client supplies a
random 256-bit capability, while the server stores only its SHA-256 hash.
This prevents source-code knowledge or predictable blob IDs from granting
access to another client's namespace.
"""

import hashlib
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "private.db"

router = APIRouter(prefix="/api/private", tags=["private"])

MAX_BLOB = 4_000_000
MAX_LIMIT = 100
CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
BLOB_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ID_RE = re.compile(r"^[0-9a-f]{64}$")


class EncryptedBlob(BaseModel):
    blob: str = Field(min_length=1, max_length=MAX_BLOB)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS blobs ("
        "id TEXT PRIMARY KEY, capability_hash TEXT NOT NULL, blob TEXT NOT NULL, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    # Existing development databases from the pre-capability implementation
    # may lack the namespace column. Do not silently expose those rows.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(blobs)")}
    if "capability_hash" not in columns:
        conn.execute("ALTER TABLE blobs ADD COLUMN capability_hash TEXT")
        conn.commit()
    return conn


def validate_capability(value: str | None) -> str:
    if not value or not CAPABILITY_RE.fullmatch(value):
        raise HTTPException(status_code=401, detail="A valid private capability is required.")
    return value


def capability_hash(capability: str) -> str:
    return hashlib.sha256(capability.encode("ascii")).hexdigest()


def blob_id(blob: str) -> str:
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


@router.post("/blobs")
def put_blob(payload: EncryptedBlob, x_private_capability: str | None = Header(default=None)):
    capability = validate_capability(x_private_capability)
    if not BLOB_RE.fullmatch(payload.blob):
        raise HTTPException(status_code=400, detail="Invalid ciphertext")
    ident = blob_id(payload.blob)
    conn = db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO blobs(id, capability_hash, blob) VALUES(?, ?, ?)",
            (ident, capability_hash(capability), payload.blob),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": ident}


@router.get("/blobs")
def list_blobs(
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    x_private_capability: str | None = Header(default=None),
):
    capability = validate_capability(x_private_capability)
    conn = db()
    try:
        rows = conn.execute(
            "SELECT id, blob FROM blobs WHERE capability_hash=? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (capability_hash(capability), limit),
        ).fetchall()
    finally:
        conn.close()
    return {"results": [{"id": row[0], "blob": row[1]} for row in rows]}


@router.get("/blobs/{ident}")
def get_blob(ident: str, x_private_capability: str | None = Header(default=None)):
    capability = validate_capability(x_private_capability)
    if not ID_RE.fullmatch(ident):
        raise HTTPException(status_code=400, detail="Invalid blob id")
    conn = db()
    try:
        row = conn.execute(
            "SELECT blob FROM blobs WHERE id=? AND capability_hash=?",
            (ident, capability_hash(capability)),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Blob not found")
    return {"id": ident, "blob": row[0]}
