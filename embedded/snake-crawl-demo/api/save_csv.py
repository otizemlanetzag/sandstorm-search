"""Persist crawler rows into DATA.CSV in the GitHub repository."""
import base64
import csv
import io
import json
import os
import urllib.request
from .security import valid_session

REPO = os.environ.get("GITHUB_REPOSITORY", "otizemlanetzag/snake-crawl")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

FIELDS = ["url","final_url","status","content_type","title","description","text","links","depth","crawled_at","content"]

def _github(path, method="GET", body=None):
    url = "https://api.github.com/repos/" + REPO + "/contents/" + path
    if "?" not in url:
        url += "?ref=" + BRANCH
    headers = {"Accept":"application/vnd.github+json","User-Agent":"Snake-Crawl/1.0"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())

def _csv(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()

def _handle_request(request):
    if request.method != "POST":
        return {"statusCode":405,"body":json.dumps({"error":"POST required"})}
    if not valid_session(request):
        return {"statusCode":401,"body":json.dumps({"error":"Authentication required"})}
    if not TOKEN:
        return {"statusCode":500,"body":json.dumps({"error":"GITHUB_TOKEN is not configured"})}
    try:
        body = request.body
        if isinstance(body, bytes):
            body = body.decode()
        payload = json.loads(body or "{}")
        rows = payload.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return {"statusCode":400,"body":json.dumps({"error":"rows must be a non-empty list"})}

        try:
            current = _github("DATA.CSV")
            current_csv = base64.b64decode(current["content"].replace("\n","")).decode("utf-8-sig")
            existing = list(csv.DictReader(io.StringIO(current_csv)))
            sha = current["sha"]
        except Exception as exc:
            return {"statusCode": 502, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Unable to read DATA.CSV from GitHub: " + str(exc)})}

        # Avoid duplicating rows when the browser retries a batch.
        seen = {(r.get("url",""), str(r.get("status","")), r.get("crawled_at","")) for r in existing}
        for row in rows:
            key = (str(row.get("url","")), str(row.get("status","")), str(row.get("crawled_at","")))
            if key not in seen:
                existing.append({f: row.get(f,"") for f in FIELDS})
                seen.add(key)

        content = base64.b64encode(_csv(existing).encode("utf-8-sig")).decode()
        commit = {"message":"Update DATA.CSV from crawler","content":content,"branch":BRANCH}
        if sha:
            commit["sha"] = sha
        result = _github("DATA.CSV", "PUT", commit)
        return {"statusCode":200,"headers":{"Content-Type":"application/json"},"body":json.dumps({"saved":len(rows),"total":len(existing),"commit":result.get("commit",{}).get("sha")})}
    except Exception as exc:
        return {"statusCode":500,"headers":{"Content-Type":"application/json"},"body":json.dumps({"error":str(exc)})}

