from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from warcio.archiveiterator import ArchiveIterator

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "search.db"
CC_INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-34-index"
UA = "SandstormSearch/0.3 (+https://github.com/otizemlanetzag/sandstorm-search)"


def database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
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
    return title[:500], description[:1000], text[:500000], soup


def discover_links(soup: BeautifulSoup, base_url: str, max_links: int = 100):
    found = []
    seen = set()
    for tag in soup.find_all("a", href=True):
        raw = tag.get("href", "").strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        try:
            parsed = urlparse(urljoin(base_url, raw))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            url = parsed._replace(fragment="").geturl()
            if url not in seen:
                seen.add(url)
                found.append(url)
                if len(found) >= max_links:
                    break
        except ValueError:
            continue
    return found


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
    r = requests.get(
        "https://data.commoncrawl.org/" + filename,
        headers={
            "Range": f"bytes={offset}-{offset + length - 1}",
            "Accept-Encoding": "identity",
            "User-Agent": UA,
        },
        timeout=90,
    )
    r.raise_for_status()
    data = r.content
    if len(data) != length:
        raise RuntimeError(f"unexpected WARC range size: {len(data)} != {length}")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        for warc in ArchiveIterator(gz):
            if warc.rec_type == "response":
                return warc.content_stream().read()
    return b""


def index(pattern: str, limit: int, discover: bool = False):
    conn = database()
    count = 0
    discovered = set()
    try:
        for rec in query_index(pattern, limit):
            try:
                url = rec["url"]
                if conn.execute("SELECT 1 FROM pages WHERE url=? LIMIT 1", (url,)).fetchone():
                    continue
                body = fetch_warc(rec)
                if not body:
                    continue
                title, description, text, soup = parse_html(body)
                domain = urlparse(url).netloc.lower()
                conn.execute(
                    "INSERT INTO pages(url,title,description,content,domain,crawled_at) VALUES(?,?,?,?,?,?)",
                    (url, title, description, text, domain, rec.get("timestamp", "")),
                )
                count += 1
                if discover:
                    discovered.update(discover_links(soup, url, 50))
                if count % 10 == 0:
                    conn.commit()
                    print(f"indexed {count}; discovered {len(discovered)} links")
            except Exception as exc:
                print(f"skip {rec.get('url')}: {exc}")
        conn.commit()
    finally:
        conn.close()
    print(f"done: {count} pages; discovered {len(discovered)} links")
    return discovered


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Sandstorm's SQLite FTS index from Common Crawl")
    parser.add_argument("pattern", nargs="?", default="*.example.com/*")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--discover-links", action="store_true")
    args = parser.parse_args()
    index(args.pattern, args.limit, args.discover_links)
