from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler

import psycopg
from psycopg.rows import dict_row

ACCOUNT_ID_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
SESSION_TTL = 60 * 60 * 24 * 30
MAX_BODY = 12000
PBKDF2_ITERATIONS = 600000

def db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, connect_timeout=8, row_factory=dict_row)

def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_accounts (
                    account_id TEXT PRIMARY KEY,
                    client_salt BYTEA NOT NULL,
                    verifier_salt BYTEA NOT NULL,
                    verifier BYTEA NOT NULL,
                    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_sessions (
                    token_hash BYTEA PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS sandstorm_sessions_account_idx ON sandstorm_sessions(account_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS sandstorm_sessions_expiry_idx ON sandstorm_sessions(expires_at)")
        conn.commit()

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def valid_account_id(value: str) -> bool:
    return bool(ACCOUNT_ID_RE.fullmatch(value or ""))

def valid_proof(value: str) -> bool:
    try:
        raw = unb64(value)
        return len(raw) == 32
    except Exception:
        return False

def client_proof(secret: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)

def verifier_for(proof: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(proof, salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)

def json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > MAX_BODY:
        raise ValueError("Invalid request size")
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))

def cookie_token(handler):
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("Cookie", ""))
    morsel = cookie.get("sandstorm_session")
    return morsel.value if morsel else ""

def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()

def make_session(account_id: str) -> str:
    token = secrets.token_urlsafe(48)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sandstorm_sessions WHERE expires_at < NOW()")
            cur.execute(
                "INSERT INTO sandstorm_sessions(token_hash, account_id, expires_at) VALUES (%s,%s,NOW() + INTERVAL '30 days')",
                (token_hash(token), account_id),
            )
        conn.commit()
    return token

def current_account(handler):
    token = cookie_token(handler)
    if not token:
        return None
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.account_id, a.settings
                FROM sandstorm_sessions s
                JOIN sandstorm_accounts a ON a.account_id=s.account_id
                WHERE s.token_hash=%s AND s.expires_at>NOW()
            """, (token_hash(token),))
            return cur.fetchone()

def response(handler, payload, status=200, cookie=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.wfile.write(body)

def handler_main(handler: BaseHTTPRequestHandler):
    try:
        init_db()
        action = handler.path.split("?", 1)[0].rstrip("/").split("/")[-1]
        data = json_body(handler) if handler.command in ("POST", "PUT") else {}

        if action == "challenge" and handler.command == "POST":
            account_id = data.get("account_id", "")
            if not valid_account_id(account_id):
                return response(handler, {"error": "Invalid account identifier."}, 400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT client_salt FROM sandstorm_accounts WHERE account_id=%s", (account_id,))
                    row = cur.fetchone()
            if row:
                return response(handler, {"exists": True, "client_salt": b64(bytes(row["client_salt"]))})
            return response(handler, {"exists": False, "client_salt": b64(secrets.token_bytes(32))})

        if action == "register" and handler.command == "POST":
            account_id = data.get("account_id", "")
            client_salt = unb64(data.get("client_salt", ""))
            proof = unb64(data.get("proof", ""))
            if not valid_account_id(account_id) or len(client_salt) != 32 or len(proof) != 32:
                return response(handler, {"error": "Invalid account data."}, 400)
            verifier_salt = secrets.token_bytes(32)
            verifier = verifier_for(proof, verifier_salt)
            settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM sandstorm_accounts WHERE account_id=%s", (account_id,))
                    if cur.fetchone():
                        return response(handler, {"error": "Account already exists."}, 409)
                    cur.execute("""
                        INSERT INTO sandstorm_accounts(account_id,client_salt,verifier_salt,verifier,settings)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (account_id, client_salt, verifier_salt, verifier, json.dumps(settings)))
                conn.commit()
            token = make_session(account_id)
            return response(handler, {"ok": True, "settings": settings}, 201,
                            f"sandstorm_session={token}; Max-Age={SESSION_TTL}; Path=/; HttpOnly; Secure; SameSite=Lax")

        if action == "login" and handler.command == "POST":
            account_id = data.get("account_id", "")
            proof = unb64(data.get("proof", ""))
            if not valid_account_id(account_id) or len(proof) != 32:
                return response(handler, {"error": "Invalid account data."}, 400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT verifier_salt, verifier, settings FROM sandstorm_accounts WHERE account_id=%s", (account_id,))
                    row = cur.fetchone()
            if not row:
                return response(handler, {"error": "המשפט הסודי אינו מזוהה."}, 401)
            candidate = verifier_for(proof, bytes(row["verifier_salt"]))
            if not hmac.compare_digest(candidate, bytes(row["verifier"])):
                return response(handler, {"error": "המשפט הסודי אינו מזוהה."}, 401)
            token = make_session(account_id)
            return response(handler, {"ok": True, "settings": row["settings"] or {}}, 200,
                            f"sandstorm_session={token}; Max-Age={SESSION_TTL}; Path=/; HttpOnly; Secure; SameSite=Lax")

        if action == "me" and handler.command == "GET":
            account = current_account(handler)
            if not account:
                return response(handler, {"logged_in": False})
            return response(handler, {"logged_in": True, "settings": account["settings"] or {}})

        if action == "settings" and handler.command == "PUT":
            account = current_account(handler)
            if not account:
                return response(handler, {"error": "Not signed in."}, 401)
            settings = data.get("settings")
            if not isinstance(settings, dict):
                return response(handler, {"error": "Invalid settings."}, 400)
            settings = {k: v for k, v in settings.items() if k in ("location", "saveLocation", "autoMap")}
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sandstorm_accounts SET settings=%s,updated_at=NOW() WHERE account_id=%s",
                                (json.dumps(settings), account["account_id"]))
                conn.commit()
            return response(handler, {"ok": True, "settings": settings})

        if action == "logout" and handler.command == "POST":
            token = cookie_token(handler)
            if token:
                with db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM sandstorm_sessions WHERE token_hash=%s", (token_hash(token),))
                    conn.commit()
            return response(handler, {"ok": True}, 200,
                            "sandstorm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax")

        return response(handler, {"error": "Not found"}, 404)
    except (json.JSONDecodeError, ValueError, UnicodeError):
        return response(handler, {"error": "Invalid request."}, 400)
    except Exception:
        return response(handler, {"error": "Account service is not configured or temporarily unavailable."}, 503)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/account/me"):
            handler_main(self)
        else:
            response(self, {"error": "Not found"}, 404)
    def do_POST(self):
        if self.path.startswith(("/api/account/challenge","/api/account/register","/api/account/login","/api/account/logout")):
            handler_main(self)
        else:
            response(self, {"error": "Not found"}, 404)
    def do_PUT(self):
        if self.path.startswith("/api/account/settings"):
            handler_main(self)
        else:
            response(self, {"error": "Not found"}, 404)
    def log_message(self, format, *args):
        return
