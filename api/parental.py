from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler

import psycopg
from psycopg.rows import dict_row
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_BODY = 4_000_000
PAIR_TTL_SECONDS = 10 * 60
PROOF_MAX_BYTES = 3_000_000


def db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, connect_timeout=8, row_factory=dict_row)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def cookie_token(handler):
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("Cookie", ""))
    morsel = cookie.get("sandstorm_session")
    return morsel.value if morsel else ""


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


def response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def body(handler):
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > MAX_BODY:
        raise ValueError("Invalid request size")
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def code_hash(code: str) -> bytes:
    return hashlib.scrypt(code.encode(), salt=bytes.fromhex(os.environ.get("PARENTAL_CODE_SALT", "00" * 32)),
                          n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def encryption_key() -> bytes:
    secret = os.environ.get("PARENTAL_MASTER_KEY")
    if not secret:
        raise RuntimeError("PARENTAL_MASTER_KEY is not configured")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_code(code: str) -> bytes:
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(encryption_key()).encrypt(nonce, code.encode(), None)
    return nonce + encrypted


def decrypt_code(blob: bytes) -> str:
    return AESGCM(encryption_key()).decrypt(blob[:12], blob[12:], None).decode()


def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_parental_links (
                    link_id TEXT PRIMARY KEY,
                    child_account_id TEXT NOT NULL UNIQUE REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    supervisor_account_id TEXT NOT NULL REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    birth_date DATE NOT NULL,
                    child_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                    safe_search BOOLEAN NOT NULL DEFAULT TRUE,
                    release_code_hash BYTEA NOT NULL,
                    release_code_enc BYTEA NOT NULL,
                    reveal_after TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    stopped_at TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_parental_pairings (
                    pairing_token_hash BYTEA PRIMARY KEY,
                    child_account_id TEXT NOT NULL REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    birth_date DATE NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_parental_proofs (
                    proof_id TEXT PRIMARY KEY,
                    child_account_id TEXT NOT NULL REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    supervisor_account_id TEXT NOT NULL REFERENCES sandstorm_accounts(account_id) ON DELETE CASCADE,
                    proof_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    content BYTEA NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending_review',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()


def active_link_for(account_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM sandstorm_parental_links
                WHERE (child_account_id=%s OR supervisor_account_id=%s)
                  AND stopped_at IS NULL
            """, (account_id, account_id))
            row = cur.fetchone()
    if row and row["birth_date"] <= date(date.today().year - 18, date.today().month, date.today().day):
        stop_link(row["link_id"])
        return None
    return row


def stop_link(link_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sandstorm_parental_links SET stopped_at=NOW() WHERE link_id=%s AND stopped_at IS NULL", (link_id,))
        conn.commit()


def handler_main(handler):
    try:
        init_db()
        path = handler.path.split("?", 1)[0].rstrip("/")
        action = path.split("/")[-1]
        account = current_account(handler)

        if not account:
            return response(handler, {"error": "יש להתחבר לחשבון."}, 401)

        if action == "status" and handler.command == "GET":
            link = active_link_for(account["account_id"])
            if not link:
                return response(handler, {"linked": False})
            is_child = link["child_account_id"] == account["account_id"]
            return response(handler, {
                "linked": True,
                "role": "SUPERVISED" if is_child else "SUPERVISOR",
                "safe_search": bool(link["safe_search"]),
                "child_confirmed": bool(link["child_confirmed"]),
                "birth_date": link["birth_date"].isoformat(),
            })

        data = body(handler) if handler.command == "POST" else {}

        if action == "create-pairing" and handler.command == "POST":
            birth = data.get("birth_date", "")
            if not isinstance(birth, str):
                return response(handler, {"error": "תאריך לידה לא תקין."}, 400)
            try:
                birth_date = date.fromisoformat(birth)
            except ValueError:
                return response(handler, {"error": "תאריך לידה לא תקין."}, 400)
            if birth_date > date.today():
                return response(handler, {"error": "תאריך הלידה לא יכול להיות בעתיד."}, 400)
            existing = active_link_for(account["account_id"])
            if existing:
                return response(handler, {"error": "החשבון כבר נמצא בפיקוח."}, 409)
            token = secrets.token_urlsafe(32)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM sandstorm_parental_pairings WHERE expires_at<NOW()")
                    cur.execute("""
                        INSERT INTO sandstorm_parental_pairings(pairing_token_hash,child_account_id,birth_date,expires_at)
                        VALUES (%s,%s,%s,NOW()+INTERVAL '10 minutes')
                    """, (token_hash(token), account["account_id"], birth_date))
                conn.commit()
            return response(handler, {"ok": True, "pairing_token": token, "expires_in": PAIR_TTL_SECONDS})

        if action == "link" and handler.command == "POST":
            token = data.get("pairing_token", "")
            if not isinstance(token, str) or len(token) < 20:
                return response(handler, {"error": "קוד QR לא תקין."}, 400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM sandstorm_parental_pairings
                        WHERE pairing_token_hash=%s AND expires_at>NOW()
                    """, (token_hash(token),))
                    pairing = cur.fetchone()
            if not pairing or pairing["child_account_id"] == account["account_id"]:
                return response(handler, {"error": "קוד החיבור אינו תקף."}, 400)
            existing = active_link_for(account["account_id"])
            if existing:
                return response(handler, {"error": "החשבון כבר מחובר לפיקוח."}, 409)
            release_code = f"{secrets.randbelow(10000):04d}"
            link_id = secrets.token_urlsafe(24)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO sandstorm_parental_links
                        (link_id,child_account_id,supervisor_account_id,birth_date,child_confirmed,
                         safe_search,release_code_hash,release_code_enc,reveal_after)
                        VALUES (%s,%s,%s,%s,TRUE,TRUE,%s,%s,NOW()+INTERVAL '10 seconds')
                    """, (link_id, pairing["child_account_id"], account["account_id"], pairing["birth_date"],
                          code_hash(release_code), encrypt_code(release_code)))
                    cur.execute("DELETE FROM sandstorm_parental_pairings WHERE pairing_token_hash=%s", (token_hash(token),))
                conn.commit()
            return response(handler, {"ok": True, "link_id": link_id, "release_available_after": 10})

        if action == "reveal-code" and handler.command == "GET":
            link = active_link_for(account["account_id"])
            if not link or link["supervisor_account_id"] != account["account_id"]:
                return response(handler, {"error": "רק המפקח יכול לקבל את קוד השחרור."}, 403)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT EXTRACT(EPOCH FROM (reveal_after-NOW())) AS seconds FROM sandstorm_parental_links WHERE link_id=%s", (link["link_id"],))
                    row = cur.fetchone()
            if row and float(row["seconds"] or 0) > 0:
                return response(handler, {"error": "הקוד עדיין נעול.", "seconds_left": int(float(row["seconds"]) + 0.999)}, 425)
            return response(handler, {"ok": True, "release_code": decrypt_code(bytes(link["release_code_enc"]))})

        if action == "set-safe" and handler.command == "POST":
            link = active_link_for(account["account_id"])
            enabled = bool(data.get("enabled", True))
            if link:
                allowed = account["account_id"] in (link["child_account_id"], link["supervisor_account_id"])
                if not allowed:
                    return response(handler, {"error": "אין הרשאה."}, 403)
                with db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE sandstorm_parental_links SET safe_search=%s WHERE link_id=%s", (enabled, link["link_id"]))
                    conn.commit()
                return response(handler, {"ok": True, "safe_search": enabled})
            settings = account["settings"] or {}
            settings["safeSearch"] = enabled
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sandstorm_accounts SET settings=%s,updated_at=NOW() WHERE account_id=%s",
                                (json.dumps(settings), account["account_id"]))
                conn.commit()
            return response(handler, {"ok": True, "safe_search": enabled})

        if action == "unlock" and handler.command == "POST":
            link = active_link_for(account["account_id"])
            code = str(data.get("release_code", ""))
            if not link or link["child_account_id"] != account["account_id"]:
                return response(handler, {"error": "אין נעילת SAFESEARCH של פיקוח עבור החשבון הזה."}, 403)
            if not hmac.compare_digest(code_hash(code), bytes(link["release_code_hash"])) or not code.isdigit() or len(code) != 4:
                return response(handler, {"error": "קוד שחרור שגוי."}, 403)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sandstorm_parental_links SET safe_search=FALSE WHERE link_id=%s", (link["link_id"],))
                conn.commit()
            return response(handler, {"ok": True, "safe_search": False})

        if action == "stop" and handler.command == "POST":
            link = active_link_for(account["account_id"])
            code = str(data.get("release_code", ""))
            if not link or link["supervisor_account_id"] != account["account_id"]:
                return response(handler, {"error": "רק המפקח יכול להפסיק את הפיקוח."}, 403)
            if not hmac.compare_digest(code_hash(code), bytes(link["release_code_hash"])) or not code.isdigit() or len(code) != 4:
                return response(handler, {"error": "קוד שחרור שגוי."}, 403)
            stop_link(link["link_id"])
            return response(handler, {"ok": True})

        if action == "submit-proof" and handler.command == "POST":
            link = active_link_for(account["account_id"])
            if not link or link["supervisor_account_id"] != account["account_id"]:
                return response(handler, {"error": "אין הרשאה להגיש הוכחה."}, 403)
            proof_type = data.get("proof_type")
            if proof_type not in ("donation_receipt", "volunteer_form"):
                return response(handler, {"error": "סוג הוכחה לא תקין."}, 400)
            filename = str(data.get("file_name", "proof.bin"))[:180]
            mime = str(data.get("mime_type", "application/octet-stream"))[:120]
            encoded = data.get("content_base64", "")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception:
                return response(handler, {"error": "קובץ לא תקין."}, 400)
            if not raw or len(raw) > PROOF_MAX_BYTES:
                return response(handler, {"error": "הקובץ גדול מדי. המגבלה היא 3MB."}, 400)
            proof_id = secrets.token_urlsafe(18)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO sandstorm_parental_proofs
                        (proof_id,child_account_id,supervisor_account_id,proof_type,file_name,mime_type,content)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """, (proof_id, link["child_account_id"], link["supervisor_account_id"],
                          proof_type, filename, mime, raw))
                conn.commit()
            return response(handler, {"ok": True, "proof_id": proof_id, "status": "pending_review"})

        if action == "proofs" and handler.command == "GET":
            link = active_link_for(account["account_id"])
            if not link:
                return response(handler, {"proofs": []})
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT proof_id,proof_type,file_name,mime_type,status,created_at
                        FROM sandstorm_parental_proofs
                        WHERE child_account_id=%s AND supervisor_account_id=%s
                        ORDER BY created_at DESC
                    """, (link["child_account_id"], link["supervisor_account_id"]))
                    rows = cur.fetchall()
            return response(handler, {"proofs": [dict(x) for x in rows]})

        return response(handler, {"error": "Not found"}, 404)
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return response(handler, {"error": "בקשה לא תקינה."}, 400)
    except Exception:
        return response(handler, {"error": "שירות בקרת ההורים אינו זמין כרגע."}, 503)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith(("/api/parental/status", "/api/parental/reveal-code", "/api/parental/proofs")):
            handler_main(self)
        else:
            response(self, {"error": "Not found"}, 404)

    def do_POST(self):
        if self.path.startswith(("/api/parental/create-pairing", "/api/parental/link", "/api/parental/set-safe",
                                 "/api/parental/unlock", "/api/parental/stop", "/api/parental/submit-proof")):
            handler_main(self)
        else:
            response(self, {"error": "Not found"}, 404)

    def log_message(self, format, *args):
        return
