import json
import os
from .security import session_cookie

def _secret():
    return os.environ.get("SNAKE_CRAWL_SECRET", "").strip()

def _handle_request(request):
    if request.method != "POST":
        return {"statusCode": 405, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "POST only"})}
    try:
        body = request.body if isinstance(request.body, dict) else json.loads(request.body or "{}")
        supplied = str(body.get("code", "")).strip()
        secret = _secret()
        ok = bool(secret) and supplied == secret
        return {
            "statusCode": 200 if ok else 401,
            "headers": {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "Set-Cookie": session_cookie() if ok else "",
            },
            "body": json.dumps({"authenticated": ok}),
        }
    except Exception:
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"authenticated": False})}
