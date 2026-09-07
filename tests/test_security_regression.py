from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import private_store
from backend.main import app

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FUNCTION = ROOT / "netlify" / "functions" / "private.mjs"
SEARCH_FUNCTION = ROOT / "netlify" / "functions" / "search.mjs"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(private_store, "DB", tmp_path / "private.db")
    return TestClient(app)


def capability(seed: str = "A") -> str:
    return seed * 43


def test_private_api_requires_capability(client):
    assert client.get("/api/private/blobs").status_code == 401
    assert client.post("/api/private/blobs", json={"blob": "abc"}).status_code == 401


def test_private_api_rejects_malformed_capability(client):
    for value in ["short", "!" * 43, "A" * 42, "A" * 44]:
        response = client.get(
            "/api/private/blobs", headers={"X-Private-Capability": value}
        )
        assert response.status_code == 401


def test_private_namespace_isolation(client):
    first = capability("A")
    second = capability("B")
    blob = "abc_DEF-123"

    saved = client.post(
        "/api/private/blobs",
        headers={"X-Private-Capability": first},
        json={"blob": blob},
    )
    assert saved.status_code == 200
    ident = saved.json()["id"]

    own = client.get(
        "/api/private/blobs", headers={"X-Private-Capability": first}
    )
    assert own.status_code == 200
    assert [x["id"] for x in own.json()["results"]] == [ident]

    foreign = client.get(
        "/api/private/blobs", headers={"X-Private-Capability": second}
    )
    assert foreign.status_code == 200
    assert foreign.json()["results"] == []

    direct_foreign = client.get(
        f"/api/private/blobs/{ident}",
        headers={"X-Private-Capability": second},
    )
    assert direct_foreign.status_code == 404


def test_private_api_rejects_invalid_ciphertext(client):
    headers = {"X-Private-Capability": capability()}
    for blob in ["hello world", "<script>alert(1)</script>", "a/b", "a\\b"]:
        response = client.post(
            "/api/private/blobs", headers=headers, json={"blob": blob}
        )
        assert response.status_code == 400


def test_private_api_rejects_invalid_blob_ids(client):
    response = client.get(
        "/api/private/blobs/not-an-id",
        headers={"X-Private-Capability": capability()},
    )
    assert response.status_code == 400


def test_search_page_escapes_indexed_values(client, monkeypatch):
    class FakeRow(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)

    fake = [
        FakeRow(
            url="https://example.test/?q=\"x\"",
            title="<img src=x onerror=alert(1)>",
            description="<script>alert(1)</script>",
            domain="example.test",
            crawled_at="now",
        )
    ]
    monkeypatch.setattr("backend.main.search_rows", lambda q, limit: fake)
    response = client.get("/search?q=test")
    assert response.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;img" in response.text


def test_netlify_private_function_has_capability_namespace_and_no_global_listing():
    source = PRIVATE_FUNCTION.read_text(encoding="utf-8")
    assert "X-Private-Capability".lower() in source.lower()
    assert "sha256" in source
    assert "const prefix = `${capabilityHash}/`;" in source
    assert "store.list({ prefix" in source
    assert "store.list()" not in source
    assert "MAX_CURSOR = 2048" in source
    assert "cursor.length > MAX_CURSOR" in source
    assert not re.search(r"KEY_RE\.test\(cursor\)", source)


def test_netlify_search_function_has_limits_and_safe_url_scheme():
    source = SEARCH_FUNCTION.read_text(encoding="utf-8")
    assert "MAX_QUERY" in source
    assert "MAX_TERMS" in source
    assert "MAX_TERM" in source
    assert "MAX_RESULTS" in source
    assert "url.protocol !== \"http:\"" in source
    assert "url.protocol !== \"https:\"" in source
    assert "javascript:" not in source.lower().replace("https://", "")
