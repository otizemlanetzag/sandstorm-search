from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse, PlainTextResponse
from pathlib import Path

from api.auth import _handle_request as auth_request
from api.crawl import _handle_request as crawl_request
from api.advanced import _handle_request as advanced_request
from api.save_csv import _handle_request as save_request

app = FastAPI()

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).resolve().parent.parent / "index.html", media_type="text/html")

@app.get("/google6a2c4be352a15be8.html", include_in_schema=False)
def google_verification():
    return PlainTextResponse("google-site-verification: google6a2c4be352a15be8.html")

ROUTES = {
    "/api/auth": auth_request,
    "/api/crawl": crawl_request,
    "/api/advanced": advanced_request,
    "/api/save_csv": save_request,
}

async def dispatch(path: str, request: Request):
    target = ROUTES.get(path.rstrip("/"))
    if target is None:
        return Response(
            content='{"error":"Unknown API endpoint"}',
            status_code=404,
            media_type="application/json",
        )

    body = await request.body()
    proxy = type("Request", (), {
        "method": request.method,
        "headers": request.headers,
        "body": body.decode("utf-8", errors="replace"),
    })()
    result = target(proxy)

    headers = result.get("headers", {})
    return Response(
        content=result.get("body", ""),
        status_code=result.get("statusCode", 500),
        headers={k: v for k, v in headers.items() if v},
        media_type=None,
    )

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def api_route(path: str, request: Request):
    return await dispatch("/api/" + path, request)
