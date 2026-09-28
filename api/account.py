from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import sqlite3
from vercel.blob import BlobClient
from vercel.blob.errors import BlobNotFoundError

ACCOUNT_ID_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
SESSION_TTL = 60 * 60 * 24 * 30
MAX_JSON_BODY = 12000
MAX_UPLOAD = 4 * 1024 * 1024
PBKDF2_ITERATIONS = 600000
RELEASE_CODE_TTL = 60 * 60 * 24 * 365
PAIRING_TTL = 10 * 60
ALLOWED_SETTINGS = {
    "location", "saveLocation", "autoMap", "safeSearch", "resultsPerPage",
    "openNewTab", "saveSearches", "targetLanguage", "autoTranslate",
    "showWarnings", "warnBeforeHarmful", "calmMode", "fontSize",
    "language", "saveHistory", "syncSettings",
}

class _CompatCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _sql(self, sql):
        sql = sql.replace("%s", "?")
        sql = sql.replace("NOW()+INTERVAL '30 days'", "datetime('now','+30 days')")
        sql = sql.replace("NOW()+INTERVAL '10 minutes'", "datetime('now','+10 minutes')")
        sql = sql.replace("NOW()+INTERVAL '365 days'", "datetime('now','+365 days')")
        sql = sql.replace("NOW()", "CURRENT_TIMESTAMP")
        return sql.replace("::jsonb", "")

    def execute(self, sql, params=()):
        return self._cursor.execute(self._sql(sql), params)

    def executemany(self, sql, seq):
        return self._cursor.executemany(self._sql(sql), seq)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def _row(self, row):
        if row is None:
            return None
        value = {k: row[k] for k in row.keys()}
        if isinstance(value.get("settings"), str):
            try:
                value["settings"] = json.loads(value["settings"])
            except Exception:
                pass
        return value

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._cursor.__exit__(exc_type, exc, tb)

BLOB_DB_PATH = "sandstorm/account.sqlite3"
BLOB_ACCESS = "private"

class _BlobSQLite:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        raw = self._read_blob()
        if raw:
            self.conn.deserialize(raw)

    def _read_blob(self):
        try:
            with BlobClient() as client:
                result = client.get(BLOB_DB_PATH, access=BLOB_ACCESS, use_cache=False)
        except BlobNotFoundError:
            return None
        if result is None or result.status_code != 200 or result.stream is None:
            return None
        return b"".join(result.stream)

    def cursor(self):
        return _CompatCursor(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        try:
            with BlobClient() as client:
                client.put(BLOB_DB_PATH, self.conn.serialize(),
                           access=BLOB_ACCESS,
                           content_type="application/octet-stream",
                           overwrite=True)
        finally:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False

def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_accounts (
                    account_id TEXT PRIMARY KEY,
                    client_salt BLOB NOT NULL,
                    verifier_salt BLOB NOT NULL,
                    verifier BLOB NOT NULL,
                    settings TEXT NOT NULL DEFAULT '{}',
                    birth_date TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_sessions (
                    token_hash BLOB PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_supervision (
                    supervised_id TEXT PRIMARY KEY,
                    supervisor_id TEXT NOT NULL,
                    child_approved_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_pairings (
                    token_hash BLOB PRIMARY KEY,
                    supervised_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    approved_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_release_codes (
                    supervised_id TEXT PRIMARY KEY,
                    code_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sandstorm_proof_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supervised_id TEXT NOT NULL,
                    proof_type TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    file_data BLOB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

def db():
    return _BlobSQLite()

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def valid_account_id(value: str) -> bool:
    return bool(ACCOUNT_ID_RE.fullmatch(value or ""))

def verifier_for(proof: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(proof, salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)

def json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0 or length > MAX_JSON_BODY:
        raise ValueError("Invalid request size")
    return json.loads(handler.rfile.read(length).decode("utf-8"))

def cookie_token(handler):
    cookie = SimpleCookie()
    cookie.load(handler.headers.get("Cookie", ""))
    morsel = cookie.get("sandstorm_session")
    return morsel.value if morsel else ""

def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()

def make_session(account_id: str) -> str:
    token = secrets.token_urlsafe(48)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sandstorm_sessions WHERE expires_at < NOW()")
            cur.execute("INSERT INTO sandstorm_sessions(token_hash,account_id,expires_at) VALUES (%s,%s,NOW()+INTERVAL '30 days')",
                        (token_hash(token), account_id))
        conn.commit()
    return token

def current_account(handler):
    token = cookie_token(handler)
    if not token:
        return None
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.account_id,a.settings,a.birth_date,
                       s.supervised_id,s.supervisor_id,s.child_approved_at
                FROM sandstorm_sessions ss
                JOIN sandstorm_accounts a ON a.account_id=ss.account_id
                LEFT JOIN sandstorm_supervision s
                  ON (s.supervised_id=a.account_id OR s.supervisor_id=a.account_id) AND s.active=TRUE
                WHERE ss.token_hash=%s AND ss.expires_at>NOW()
                LIMIT 1
            """, (token_hash(token),))
            return cur.fetchone()

def response(handler, payload, status=200, cookie=None):
    body=json.dumps(payload,ensure_ascii=False,default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type","application/json; charset=utf-8")
    handler.send_header("Cache-Control","no-store")
    handler.send_header("X-Content-Type-Options","nosniff")
    handler.send_header("Content-Length",str(len(body)))
    if cookie is not None:
        handler.send_header("Set-Cookie",cookie)
    handler.end_headers()
    handler.wfile.write(body)

def supervision_for(account_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sandstorm_supervision WHERE (supervised_id=%s OR supervisor_id=%s) AND active=TRUE", (account_id, account_id))
            return cur.fetchone()

def make_pairing(supervised_id):
    raw=secrets.token_urlsafe(32)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sandstorm_pairings WHERE expires_at<NOW() OR used=TRUE")
            cur.execute("INSERT INTO sandstorm_pairings(token_hash,supervised_id,expires_at) VALUES(%s,%s,NOW()+INTERVAL '10 minutes')",
                        (token_hash(raw),supervised_id))
        conn.commit()
    return raw

def new_release_code(supervised_id):
    code=f"{secrets.randbelow(10000):04d}"
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sandstorm_release_codes(supervised_id,code_hash)
                VALUES(%s,%s)
                ON CONFLICT(supervised_id) DO UPDATE SET code_hash=EXCLUDED.code_hash,created_at=NOW()
            """,(supervised_id,hashlib.sha256(code.encode()).digest()))
        conn.commit()
    return code

def code_ok(supervised_id,code):
    if not __import__("re").fullmatch(r"\d{4}",code or ""):
        return False
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code_hash FROM sandstorm_release_codes WHERE supervised_id=%s AND created_at>datetime('now','-365 days')",(supervised_id,))
            row=cur.fetchone()
    return bool(row and hmac.compare_digest(bytes(row["code_hash"]),hashlib.sha256(code.encode()).digest()))

def adult(birth_date):
    if not birth_date:
        return False
    if isinstance(birth_date, str):
        try:
            birth_date = date.fromisoformat(birth_date)
        except ValueError:
            return False
    today=date.today()
    return (today.year-birth_date.year) - ((today.month,today.day)<(birth_date.month,birth_date.day)) >= 18

def unlink_if_adult(account_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT birth_date FROM sandstorm_accounts WHERE account_id=%s",(account_id,))
            row=cur.fetchone()
            if row and adult(row["birth_date"]):
                cur.execute("UPDATE sandstorm_supervision SET active=FALSE WHERE supervised_id=%s",(account_id,))
                conn.commit()
                return True
    return False

def settings_for(raw):
    if not isinstance(raw,dict): return {}
    return {k:v for k,v in raw.items() if k in ALLOWED_SETTINGS}

def multipart_upload(handler):
    length=int(handler.headers.get("Content-Length","0") or 0)
    if length<=0 or length>MAX_UPLOAD:
        raise ValueError("Invalid upload size")
    ctype=handler.headers.get("Content-Type","")
    if not ctype.startswith("multipart/form-data;"):
        raise ValueError("Multipart upload required")
    boundary=ctype.split("boundary=",1)[-1].strip().strip('"')
    raw=handler.rfile.read(length)
    marker=("--"+boundary).encode()
    parts=raw.split(marker)
    fields={}
    file_part=None
    for part in parts:
        if not part or part in (b"--\r\n",b"--"):
            continue
        part=part.lstrip(b"\r\n").rstrip(b"\r\n")
        head,sep,body=part.partition(b"\r\n\r\n")
        if not sep: continue
        headers=head.decode("utf-8","replace").split("\r\n")
        disp=next((h for h in headers if h.lower().startswith("content-disposition:")), "")
        name=""
        filename=""
        for piece in disp.split(";"):
            piece=piece.strip()
            if piece.startswith("name="): name=piece[5:].strip('"')
            elif piece.startswith("filename="): filename=piece[9:].strip('"')
        ctype2=next((h.split(":",1)[1].strip() for h in headers if h.lower().startswith("content-type:")), "application/octet-stream")
        if filename:
            file_part=(name,filename,ctype2,body)
        else:
            fields[name]=body.decode("utf-8","replace")
    if not file_part: raise ValueError("No proof file")
    return fields,file_part

def handler_main(handler):
    try:
        init_db()
        path=urlparse(handler.path).path
        action=path.rstrip("/").split("/")[-1]
        data=json_body(handler) if handler.command in ("POST","PUT") and "proof-upload" not in path else {}

        if action=="challenge" and handler.command=="POST":
            aid=data.get("account_id","")
            if not valid_account_id(aid): return response(handler,{"error":"Invalid account identifier."},400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT client_salt FROM sandstorm_accounts WHERE account_id=%s",(aid,))
                    row=cur.fetchone()
            return response(handler,{"exists":bool(row),"client_salt":b64(bytes(row["client_salt"])) if row else b64(secrets.token_bytes(32))})

        if action=="register" and handler.command=="POST":
            aid=data.get("account_id",""); cs=unb64(data.get("client_salt","")); proof=unb64(data.get("proof",""))
            if not valid_account_id(aid) or len(cs)!=32 or len(proof)!=32:return response(handler,{"error":"Invalid account data."},400)
            birth=None
            if data.get("birth_date"):
                birth=date.fromisoformat(data["birth_date"])
            settings=settings_for(data.get("settings",{}))
            vs=secrets.token_bytes(32); verifier=verifier_for(proof,vs)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM sandstorm_accounts WHERE account_id=%s",(aid,))
                    if cur.fetchone(): return response(handler,{"error":"Account already exists."},409)
                    cur.execute("INSERT INTO sandstorm_accounts(account_id,client_salt,verifier_salt,verifier,settings,birth_date) VALUES(%s,%s,%s,%s,%s,%s)",
                                (aid,cs,vs,verifier,json.dumps(settings),birth))
                conn.commit()
            token=make_session(aid)
            return response(handler,{"ok":True,"settings":settings},201,
                            f"sandstorm_session={token}; Max-Age={SESSION_TTL}; Path=/; HttpOnly; Secure; SameSite=Lax")

        if action=="login" and handler.command=="POST":
            aid=data.get("account_id",""); proof=unb64(data.get("proof",""))
            if not valid_account_id(aid) or len(proof)!=32:return response(handler,{"error":"Invalid account data."},400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT verifier_salt,verifier,settings FROM sandstorm_accounts WHERE account_id=%s",(aid,))
                    row=cur.fetchone()
            if not row:return response(handler,{"error":"המשפט הסודי אינו מזוהה."},401)
            if not hmac.compare_digest(verifier_for(proof,bytes(row["verifier_salt"])),bytes(row["verifier"])):return response(handler,{"error":"המשפט הסודי אינו מזוהה."},401)
            token=make_session(aid)
            return response(handler,{"ok":True,"settings":row["settings"] or {}},200,
                            f"sandstorm_session={token}; Max-Age={SESSION_TTL}; Path=/; HttpOnly; Secure; SameSite=Lax")

        if action=="me" and handler.command=="GET":
            acc=current_account(handler)
            if not acc:return response(handler,{"logged_in":False})
            if unlink_if_adult(acc["account_id"]): acc= current_account(handler)
            sup=supervision_for(acc["account_id"])
            role=None
            if sup: role="SUPERVISED" if sup["supervised_id"]==acc["account_id"] else "SUPERVISOR"
            return response(handler,{"logged_in":True,"settings":acc["settings"] or {},"birth_date":acc["birth_date"],"supervision":{"role":role,"supervised_id":sup["supervised_id"] if sup else None,"supervisor_id":sup["supervisor_id"] if sup else None,"child_approved":bool(sup and sup["child_approved_at"])},"adult_release":bool(acc["birth_date"] and adult(acc["birth_date"]))})

        if action=="settings" and handler.command=="PUT":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            settings=settings_for(data.get("settings",{}))
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sandstorm_accounts SET settings=%s,updated_at=NOW() WHERE account_id=%s",(json.dumps(settings),acc["account_id"]))
                conn.commit()
            return response(handler,{"ok":True,"settings":settings})

        if action=="pairing" and handler.command=="POST":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            if data.get("role")!="SUPERVISED": return response(handler,{"error":"Choose SUPERVISED on the child's account."},400)
            birth=data.get("birth_date")
            if birth:
                try: bd=date.fromisoformat(birth)
                except ValueError:return response(handler,{"error":"Invalid birth date."},400)
                with db() as conn:
                    with conn.cursor() as cur: cur.execute("UPDATE sandstorm_accounts SET birth_date=%s WHERE account_id=%s",(bd,acc["account_id"]))
                    conn.commit()
            token=make_pairing(acc["account_id"])
            return response(handler,{"ok":True,"pairing_token":token,"expires_seconds":PAIRING_TTL})

        if action=="pair" and handler.command=="POST":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            raw=data.get("pairing_token","")
            if not raw:return response(handler,{"error":"Missing pairing token."},400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT supervised_id FROM sandstorm_pairings WHERE token_hash=%s AND expires_at>NOW() AND used=FALSE AND approved_at IS NOT NULL",(token_hash(raw),))
                    row=cur.fetchone()
                    if not row:return response(handler,{"error":"QR code expired or already used."},400)
                    cur.execute("UPDATE sandstorm_pairings SET used=TRUE WHERE token_hash=%s",(token_hash(raw),))
                    cur.execute("UPDATE sandstorm_supervision SET active=FALSE WHERE supervisor_id=%s AND active=TRUE",(acc["account_id"],))
                    cur.execute("INSERT INTO sandstorm_supervision(supervised_id,supervisor_id,child_approved_at) VALUES(%s,%s,NOW()) ON CONFLICT(supervised_id) DO UPDATE SET supervisor_id=EXCLUDED.supervisor_id,active=TRUE,child_approved_at=EXCLUDED.child_approved_at",
                                (row["supervised_id"],acc["account_id"]))
                conn.commit()
            new_release_code(row["supervised_id"])
            return response(handler,{"ok":True})

        if action=="supervision" and handler.command=="GET":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            if unlink_if_adult(acc["account_id"]): return response(handler,{"active":False,"adult_release":True})
            sup=supervision_for(acc["account_id"])
            if not sup:return response(handler,{"active":False})
            role="SUPERVISED" if sup["supervised_id"]==acc["account_id"] else "SUPERVISOR"
            return response(handler,{"active":True,"role":role,"supervised_id":sup["supervised_id"],"supervisor_id":sup["supervisor_id"],"child_approved":bool(sup["child_approved_at"])})

        if action=="approve" and handler.command=="POST":
            acc=current_account(handler)
            token=data.get("pairing_token","")
            if not acc or not token:return response(handler,{"error":"Missing pairing approval."},400)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE sandstorm_pairings SET approved_at=NOW() WHERE token_hash=%s AND supervised_id=%s AND expires_at>NOW() AND used=FALSE",(token_hash(token),acc["account_id"]))
                    changed=cur.rowcount
                conn.commit()
            if not changed:return response(handler,{"error":"QR code expired or invalid."},400)
            return response(handler,{"ok":True})

        if action=="release-code" and handler.command=="POST":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            sup=supervision_for(acc["account_id"])
            if not sup or sup["supervisor_id"]!=acc["account_id"]:return response(handler,{"error":"Only the supervisor can request the code."},403)
            code=new_release_code(sup["supervised_id"])
            return response(handler,{"ok":True,"delay_seconds":10,"code":code})

        if action=="unlock" and handler.command=="POST":
            acc=current_account(handler); sup=supervision_for(acc["account_id"]) if acc else None
            if not acc or not sup or sup["supervised_id"]!=acc["account_id"]:return response(handler,{"error":"Only the supervised account can unlock."},403)
            if not code_ok(acc["account_id"],data.get("code","")):return response(handler,{"error":"קוד שחרור שגוי."},403)
            settings=acc["settings"] or {}; settings["safeSearch"]=False
            with db() as conn:
                with conn.cursor() as cur:cur.execute("UPDATE sandstorm_accounts SET settings=%s,updated_at=NOW() WHERE account_id=%s",(json.dumps(settings),acc["account_id"]))
                conn.commit()
            return response(handler,{"ok":True,"settings":settings})

        if action=="safe-search" and handler.command=="POST":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            enabled=bool(data.get("enabled",True)); sup=supervision_for(acc["account_id"])
            if sup and sup["supervised_id"]==acc["account_id"] and not enabled:
                return response(handler,{"error":"SAFESEARCH נעול. נדרש קוד שחרור של המפקח."},403)
            target_id=acc["account_id"]
            if sup and sup["supervisor_id"]==acc["account_id"]:
                target_id=sup["supervised_id"]
            if sup and sup["supervised_id"]==acc["account_id"] and not enabled:
                return response(handler,{"error":"SAFESEARCH נעול. נדרש קוד שחרור של המפקח."},403)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT settings FROM sandstorm_accounts WHERE account_id=%s",(target_id,))
                    row=cur.fetchone()
                    settings=row["settings"] or {}
                    settings["safeSearch"]=enabled
                    cur.execute("UPDATE sandstorm_accounts SET settings=%s,updated_at=NOW() WHERE account_id=%s",(json.dumps(settings),target_id))
                conn.commit()
            if enabled and sup:
                new_release_code(target_id)
            return response(handler,{"ok":True,"safeSearch":enabled})

        if action=="stop" and handler.command=="POST":
            acc=current_account(handler); sup=supervision_for(acc["account_id"]) if acc else None
            if not acc or not sup or sup["supervisor_id"]!=acc["account_id"]:return response(handler,{"error":"Only the supervisor can stop supervision."},403)
            if not code_ok(sup["supervised_id"],data.get("code","")):return response(handler,{"error":"קוד שחרור שגוי."},403)
            with db() as conn:
                with conn.cursor() as cur:cur.execute("UPDATE sandstorm_supervision SET active=FALSE WHERE supervised_id=%s",(sup["supervised_id"],))
                conn.commit()
            return response(handler,{"ok":True})

        if action=="proof-upload" and handler.command=="POST":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            sup=supervision_for(acc["account_id"])
            if not sup:return response(handler,{"error":"No supervision record."},403)
            fields,filep=multipart_upload(handler)
            ptype=fields.get("proof_type","")
            if ptype not in ("donation","volunteering"):return response(handler,{"error":"Invalid proof type."},400)
            _,filename,ctype,filedata=filep
            if len(filedata)>MAX_UPLOAD:return response(handler,{"error":"File too large."},413)
            if not filename or len(filename)>180:return response(handler,{"error":"Invalid filename."},400)
            with db() as conn:
                with conn.cursor() as cur:cur.execute("INSERT INTO sandstorm_proof_submissions(supervised_id,proof_type,file_name,content_type,file_data) VALUES(%s,%s,%s,%s,%s)",
                                                      (sup["supervised_id"],ptype,filename,ctype,filedata))
                conn.commit()
            return response(handler,{"ok":True,"status":"pending"})

        if action=="proofs" and handler.command=="GET":
            acc=current_account(handler)
            if not acc:return response(handler,{"error":"Not signed in."},401)
            sup=supervision_for(acc["account_id"])
            target=sup["supervised_id"] if sup else acc["account_id"]
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id,proof_type,file_name,content_type,status,created_at FROM sandstorm_proof_submissions WHERE supervised_id=%s ORDER BY id DESC",(target,))
                    rows=cur.fetchall()
            return response(handler,{"proofs":rows})

        if action=="logout" and handler.command=="POST":
            token=cookie_token(handler)
            if token:
                with db() as conn:
                    with conn.cursor() as cur:cur.execute("DELETE FROM sandstorm_sessions WHERE token_hash=%s",(token_hash(token),))
                    conn.commit()
            return response(handler,{"ok":True},200,"sandstorm_session=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax")

        return response(handler,{"error":"Not found"},404)
    except (json.JSONDecodeError,ValueError,UnicodeError):
        return response(handler,{"error":"Invalid request."},400)
    except Exception:
        return response(handler,{"error":"Account service is not configured or temporarily unavailable."},503)

class AccountHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/account/"):
            handler_main(self)
        else: response(self,{"error":"Not found"},404)
    def do_POST(self):
        if self.path.startswith("/api/account/"):
            handler_main(self)
        else: response(self,{"error":"Not found"},404)
    def do_PUT(self):
        if self.path.startswith("/api/account/"):
            handler_main(self)
        else: response(self,{"error":"Not found"},404)
    def log_message(self,format,*args):
        return
