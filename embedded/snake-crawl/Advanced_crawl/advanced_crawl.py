"""Bounded domain-discovery crawler for Snake Crawl."""
import csv
import json
import random
import re
import string
import urllib.request
from api.security import safe_public_url

DEFAULT_MAX_SITES = 100
MAX_BATCH = 10
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 OPR/120.0.0.0"
REQUEST_TIMEOUT = 5
KEYS = string.ascii_lowercase + string.digits + "-"

def _iana_tlds():
    req = urllib.request.Request("https://data.iana.org/TLD/tlds-alpha-by-domain.txt",
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        text = response.read().decode("utf-8", errors="replace")
    return [line.strip().lower() for line in text.splitlines()
            if line.strip() and not line.startswith("#")]

def make_candidate(tlds, max_characters=20):
    length = random.randint(1, min(max(1, max_characters), 20))
    label = "".join(random.choice(KEYS) for _ in range(length)).strip("-")
    if not label:
        label = random.choice(string.ascii_lowercase)
    return "https://" + label + "." + random.choice(tlds)

def fetch_candidate(url):
    try:
        if not safe_public_url(url):
            return {"url": url, "status": "blocked", "error": "Private or local address blocked"}
        req = urllib.request.Request(url, headers={"User-Agent": "Snake-Crawl/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = response.read(1_000_000)
        text = body.decode("utf-8", errors="replace")
        clean = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=re.I)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()[:100000]
        return {"url": url, "final_url": final_url, "status": status,
                "content_type": content_type, "content": clean}
    except Exception as exc:
        return {"url": url, "status": "error", "error": str(exc)}

def discover_batch(payload):
    payload = payload or {}
    count = max(1, min(MAX_BATCH, int(payload.get("count", 5))))
    max_chars = max(1, min(20, int(payload.get("max_characters", 20))))
    tlds = _iana_tlds()
    results = []
    seen = set()
    for _ in range(count):
        url = make_candidate(tlds, max_chars)
        while url in seen:
            url = make_candidate(tlds, max_chars)
        seen.add(url)
        results.append(fetch_candidate(url))
    return {"results": results, "tested": len(results),
            "found": sum(x.get("status") == 200 for x in results)}

def handle_payload(body):
    try:
        payload = body if isinstance(body, dict) else json.loads(body or "{}")
        return {"statusCode": 200,
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "body": json.dumps(discover_batch(payload), ensure_ascii=False)}
    except Exception as exc:
        return {"statusCode": 500,
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "body": json.dumps({"error": str(exc)})}

def write_csv(rows, path="DATA.CSV"):
    fields = ["url", "final_url", "status", "content_type", "content"]
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({f: row.get(f, "") for f in fields} for row in rows)

