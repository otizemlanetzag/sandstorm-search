"""Sandstorm data loader.

Downloads DATA.CSV from the snake-crawl repository when requested.
The CSV is kept in memory by default; use download_data(save_to=...) to
also save a local copy.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from pathlib import Path
from typing import Any

DATA_URL = "https://raw.githubusercontent.com/otizemlanetzag/snake-crawl/main/DATA.CSV"

USER_AGENT = "Sandstorm Search/1.0"


def download_data(save_to: str | Path | None = None) -> list[dict[str, Any]]:
    """Download DATA.CSV and return it as a list of dictionaries."""
    request = urllib.request.Request(
        DATA_URL,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read().decode("utf-8-sig")

    rows = list(csv.DictReader(io.StringIO(data)))

    if save_to is not None:
        Path(save_to).write_text(data, encoding="utf-8")

    return rows


if __name__ == "__main__":
    rows = download_data()
    print(f"Loaded {len(rows)} rows from DATA.CSV")
