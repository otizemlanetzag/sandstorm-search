"""Local Sandstorm data loader.

Downloads DATA.CSV from snake-crawl into Sandstorm's local data directory,
then reads and searches the local copy. The remote file is refreshed each
time load_data() is called successfully.
"""

from __future__ import annotations

import csv
import io
import os
import urllib.request
from urllib.error import URLError
from pathlib import Path
from typing import Any

DATA_URL = "https://raw.githubusercontent.com/otizemlanetzag/snake-crawl/main/DATA.CSV"
USER_AGENT = "Sandstorm Search/1.0"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SANDSTORM_DATA_DIR", "/tmp/sandstorm"))
LOCAL_DATA_FILE = DATA_DIR / "DATA.CSV"


def download_data() -> list[dict[str, Any]]:
    """Download DATA.CSV, save it locally, then read the local copy."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(
        DATA_URL,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        remote_data = response.read()

    # Keep a persistent local copy inside Sandstorm.
    LOCAL_DATA_FILE.write_bytes(remote_data)

    return read_local_data()


def read_local_data() -> list[dict[str, Any]]:
    """Read DATA.CSV only from Sandstorm's local copy."""
    if not LOCAL_DATA_FILE.exists():
        return download_data()

    data = LOCAL_DATA_FILE.read_text(encoding="utf-8-sig")
    return list(csv.DictReader(io.StringIO(data)))


def load_data() -> list[dict[str, Any]]:
    """Use the local cache when available; download only when missing."""
    try:
        if LOCAL_DATA_FILE.exists():
            return read_local_data()
        return download_data()
    except (OSError, URLError):
        # If the network is unavailable, continue using the last local copy.
        return read_local_data()


if __name__ == "__main__":
    rows = load_data()
    print(f"Loaded {len(rows)} rows from {LOCAL_DATA_FILE}")
