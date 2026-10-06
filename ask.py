"""Local Sandstorm data loader.

Sandstorm Search and Snake Crawl live in the same repository, so DATA.CSV is
read directly from the checked-in shared copy. No remote download is used.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DATA_FILE = BASE_DIR / "embedded" / "snake-crawl" / "DATA.CSV"


def read_local_data() -> list[dict[str, Any]]:
    if not LOCAL_DATA_FILE.is_file():
        raise FileNotFoundError(f"Shared DATA.CSV is missing: {LOCAL_DATA_FILE}")
    with LOCAL_DATA_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_data() -> list[dict[str, Any]]:
    return read_local_data()


if __name__ == "__main__":
    rows = load_data()
    print(f"Loaded {len(rows)} rows from {LOCAL_DATA_FILE}")
