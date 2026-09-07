from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from warcio.archiveiterator import ArchiveIterator

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "search.db"
# Keep this pinned to a known crawl instead of silently changing the dataset
# while an index is being built. Update deliberately when a new crawl is chosen.
CC_INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-34-index"
UA = "SandstormSearch/0.2 (+https://github.com/otizemlanetzag/sandstorm-search)"


def database():
    conn = sqlite3.connect(DB)
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
        url UNINDEXED, title, description, content,
        domain UNINDEXED, crawled_at UNINDEXED,
        tokenize='unicode61'
    )""")
    return conn


def parse_html(raw: bytes):
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = meta.get("content", "").strip() if meta else ""
    text = soup.get_text(" ", strip=True)
    return title[:500], description[:1000], text[:500000]


def query_index(pattern: str, limit: int):
    params = {
        "url": pattern,
        "output": "json",
        "filter": ["status:200", "mime:text/html"],
        "collapse": "urlkey",
        "pageSize": str(min(max(limit, 1), 100)),
    }
    r = requests.get(CC_INDEX, params=params, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    for line in r.text.splitlines():
        if line.strip():
            yield json.loads(line)


def fetch_warc(record):
    filename, offset, length = record["filename"], int(record["offset"]), int(record["length"])
    url = "https://data.commoncrawl.org/" + filename
    headers = {
        "Range": f"bytes={offset}-{offset + length - 1}",
        "Accept-Encoding": "identity",
        "User-Agent": UA,
    }
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()
    data = r.content
    if record.get("length") and len(data) != length:
        raise RuntimeError(f"unexpected WARC range size: {len(data)} != {length}")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        for warc in ArchiveIterator(gz):
            if warc.rec_type == "response":
                return warc.content_stream().read()
    return b""


def index(pattern: str, limit: int):
    conn = database()
    count = 0
    try:
        for rec in query_index(pattern, limit):
            try:
                body = fetch_warc(rec)
                if not body:
                    continue
                title, description, text = parse_html(body)
                url = rec["url"]
                domain = urlparse(url).netloc.lower()
                conn.execute(
                    "INSERT INTO pages(url,title,description,content,domain,crawled_at) VALUES(?,?,?,?,?,?)",
                    (url, title, description, text, domain, rec.get("timestamp", "")),
                )
                count += 1
                if count % 25 == 0:
                    conn.commit()
                    print(f"indexed {count}")
            except Exception as exc:
                print(f"skip {rec.get('url')}: {exc}")
        conn.commit()
    finally:
        conn.close()
    print(f"done: {count} pages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Sandstorm's SQLite FTS index from Common Crawl")
    parser.add_argument("pattern", nargs="?", default="*.example.com/*", help="Common Crawl URL pattern")
    parser.add_argument("--limit", type=int, default=100, help="maximum Common Crawl index records")
    args = parser.parse_args()
    index(args.pattern, args.limit)
