from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from .indexer import database, index_urls

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEEDS = ROOT / "data" / "index-seeds.txt"
MAX_QUEUE = 5000


def load_seeds(path: Path) -> list[str]:
    seeds: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        if "://" not in line:
            line = "https://" + line
        parsed = urlparse(line)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            seeds.append(parsed._replace(fragment="").geturl().rstrip("/"))
    return list(dict.fromkeys(seeds))


def ensure_frontier(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS crawl_frontier(
        url TEXT PRIMARY KEY,
        state TEXT NOT NULL DEFAULT 'queued',
        depth INTEGER NOT NULL DEFAULT 0,
        discovered_from TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()


def add_urls(conn: sqlite3.Connection, urls, depth: int, source: str | None = None) -> int:
    added = 0
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized = parsed._replace(fragment="").geturl()
        if len(normalized) > 2048:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO crawl_frontier(url,state,depth,discovered_from) VALUES(?,?,?,?)",
            (normalized, "queued", depth, source),
        )
        added += cur.rowcount
        if added >= MAX_QUEUE:
            break
    conn.commit()
    return added


def queued(conn: sqlite3.Connection, limit: int):
    return conn.execute(
        "SELECT url, depth FROM crawl_frontier WHERE state='queued' ORDER BY depth, updated_at LIMIT ?",
        (limit,),
    ).fetchall()


def mark(conn: sqlite3.Connection, url: str, state: str) -> None:
    conn.execute(
        "UPDATE crawl_frontier SET state=?, updated_at=CURRENT_TIMESTAMP WHERE url=?",
        (state, url),
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Sandstorm's search index using a bounded URL frontier")
    parser.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    parser.add_argument("--pages", type=int, default=25)
    parser.add_argument("--max-depth", type=int, default=2)
    args = parser.parse_args()

    conn = database()
    ensure_frontier(conn)
    seeds = load_seeds(Path(args.seeds))
    if not seeds:
        raise SystemExit("No index seeds configured")
    add_urls(conn, seeds, 0)

    processed = 0
    try:
        while processed < max(1, args.pages):
            batch = queued(conn, min(10, args.pages - processed))
            if not batch:
                break

            for url, depth in batch:
                mark(conn, url, "processing")
                try:
                    if depth > args.max_depth:
                        mark(conn, url, "done")
                        processed += 1
                        continue

                    discovered = index_urls([url], discover=True)
                    if depth < args.max_depth:
                        add_urls(conn, discovered, depth + 1, url)
                    mark(conn, url, "done")
                except Exception as exc:
                    print(f"frontier skip {url}: {exc}")
                    mark(conn, url, "failed")
                processed += 1
                if processed >= args.pages:
                    break
    finally:
        conn.close()

    print(f"refresh complete: processed {processed} frontier URLs")


if __name__ == "__main__":
    main()
