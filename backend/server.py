from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    host = os.getenv("SANDSTORM_HOST", "127.0.0.1")
    port = int(os.getenv("SANDSTORM_PORT", "8000"))
    cert = os.getenv("SANDSTORM_TLS_CERT")
    key = os.getenv("SANDSTORM_TLS_KEY")

    if bool(cert) != bool(key):
        raise SystemExit("Set both SANDSTORM_TLS_CERT and SANDSTORM_TLS_KEY, or neither.")

    kwargs = {
        "app": "backend.main:app",
        "host": host,
        "port": port,
    }
    if cert and key:
        kwargs.update({"ssl_certfile": cert, "ssl_keyfile": key})
        print(f"Sandstorm HTTPS server: https://{host}:{port}")
    else:
        print(f"Sandstorm HTTP development server: http://{host}:{port}")
        print("For encrypted browser-to-server traffic, configure TLS certificate and key.")

    uvicorn.run(**kwargs)
