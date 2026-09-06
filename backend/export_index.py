from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "search.db"
OUT = ROOT / "public" / "index.json"


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    if not DB.exists():
        print("No data/search.db found; keeping the existing public/index.json.")
        return

    from .main import db

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
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(pages)} pages to {OUT}")


if __name__ == "__main__":
    main()
