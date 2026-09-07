from __future__ import annotations

import ipaddress
import os
from pathlib import Path

import uvicorn


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise SystemExit("SANDSTORM_PORT must be an integer between 1 and 65535.") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("SANDSTORM_PORT must be an integer between 1 and 65535.")
    return port


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


if __name__ == "__main__":
    host = os.getenv("SANDSTORM_HOST", "127.0.0.1").strip()
    port = parse_port(os.getenv("SANDSTORM_PORT", "8000"))
    cert = os.getenv("SANDSTORM_TLS_CERT")
    key = os.getenv("SANDSTORM_TLS_KEY")

    if bool(cert) != bool(key):
        raise SystemExit("Set both SANDSTORM_TLS_CERT and SANDSTORM_TLS_KEY, or neither.")

    if not is_loopback(host) and not (cert and key):
        raise SystemExit(
            "Refusing to expose Sandstorm over the network without TLS. "
            "Use a loopback host for development or configure both "
            "SANDSTORM_TLS_CERT and SANDSTORM_TLS_KEY."
        )

    if cert and key:
        cert_path, key_path = Path(cert), Path(key)
        if not cert_path.is_file() or not key_path.is_file():
            raise SystemExit("SANDSTORM_TLS_CERT and SANDSTORM_TLS_KEY must point to existing files.")

    kwargs = {
        "app": "backend.main:app",
        "host": host,
        "port": port,
        "server_header": False,
        "date_header": False,
    }
    if cert and key:
        kwargs.update({"ssl_certfile": cert, "ssl_keyfile": key})
        print(f"Sandstorm HTTPS server: https://{host}:{port}")
    else:
        print(f"Sandstorm HTTP development server: http://{host}:{port}")
        print("Development mode is restricted to loopback interfaces.")

    uvicorn.run(**kwargs)
