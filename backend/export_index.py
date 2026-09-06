from __future__ import annotations

import json
from pathlib import Path

from .main import db

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "index.json"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    conn = db()
    try:
        rows = conn.execute(
            "SELECT url,title,description,content,domain,crawled_at FROM pages"
        ).fetchall()
    finally:
        conn.close()

    pages = [
        {
            "url": str(row[0]),
            "title": str(row[1] or ""),
            "description": str(row[2] or ""),
            "content": str(row[3] or ""),
            "domain": str(row[4] or ""),
            "crawled_at": str(row[5] or ""),
        }
        for row in rows
    ]
    OUT.write_text(
        json.dumps({"generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "pages": pages}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Exported {len(pages)} pages to {OUT}")


if __name__ == "__main__":
    main()
