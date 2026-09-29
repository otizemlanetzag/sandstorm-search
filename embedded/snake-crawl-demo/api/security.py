"""Shared security helpers for Snake Crawl API endpoints."""
import hashlib
import hmac
import ipaddress
import os
import socket
import time
from http.cookies import SimpleCookie

SESSION_COOKIE = "snake_session"
SESSION_TTL = 3600

def secret():
    return os.environ.get("SNAKE_CRAWL_SECRET", "").strip()

def _sign(value):
    return hmac.new(secret().encode(), value.encode(), hashlib.sha256).hexdigest()

def issue_session():
    stamp = str(int(time.time()))
    return stamp + "." + _sign(stamp)

def valid_session(request):
    s = secret()
    if not s:
        return False
    cookie = SimpleCookie()
    raw = ""
    if hasattr(request, "headers"):
        headers = request.headers or {}
        raw = headers.get("cookie", headers.get("Cookie", ""))
    try:
        cookie.load(raw)
        value = cookie[SESSION_COOKIE].value
        stamp, sig = value.split(".", 1)
        if abs(int(time.time()) - int(stamp)) > SESSION_TTL:
            return False
        return hmac.compare_digest(sig, _sign(stamp))
    except Exception:
        return False

def session_cookie():
    return f"{SESSION_COOKIE}={issue_session()}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=Strict"

def safe_public_url(url):
    """Reject non-web schemes and hostnames resolving to private/local addresses."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        host = p.hostname
        if host.lower() in ("localhost", "localhost.localdomain"):
            return False
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_multicast or ip.is_reserved or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False
