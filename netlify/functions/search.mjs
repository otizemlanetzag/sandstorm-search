import { readFile } from "node:fs/promises";

let indexPromise;
const MAX_QUERY = 300;
const MAX_TERMS = 24;
const MAX_TERM = 64;
const MAX_RESULTS = 50;
const SAFE_URL = /^(https?):$/i;

export const config = {
  path: "/api/search",
  rateLimit: {
    windowLimit: 120,
    windowSize: 60,
    aggregateBy: ["ip", "domain"]
  }
};

async function loadIndex() {
  if (!indexPromise) {
    indexPromise = readFile(new URL("../../public/index.json", import.meta.url), "utf8")
      .then(JSON.parse)
      .then(data => ({ pages: Array.isArray(data?.pages) ? data.pages : [] }))
      .catch(() => ({ pages: [] }));
  }
  return indexPromise;
}

function tokens(q) {
  return (q.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [])
    .slice(0, MAX_TERMS)
    .filter(term => term.length <= MAX_TERM);
}

function safePage(page) {
  if (!page || typeof page !== "object") return null;
  let parsed;
  try { parsed = new URL(String(page.url)); } catch { return null; }
  if (!SAFE_URL.test(parsed.protocol)) return null;
  return {
    url: parsed.href,
    title: typeof page.title === "string" ? page.title.slice(0, 500) : "",
    description: typeof page.description === "string" ? page.description.slice(0, 1000) : "",
    content: typeof page.content === "string" ? page.content.slice(0, 500000) : ""
  };
}

function score(page, terms) {
  const title = page.title.toLocaleLowerCase();
  const description = page.description.toLocaleLowerCase();
  const content = page.content.toLocaleLowerCase();
  const pageUrl = page.url.toLocaleLowerCase();
  let s = 0;
  for (const term of terms) {
    if (title.includes(term)) s += 12;
    if (description.includes(term)) s += 5;
    if (content.includes(term)) s += 1;
    if (pageUrl.includes(term)) s += 2;
  }
  return s;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer"
    }
  });
}

function htmlPage(q, results) {
  const cards = results.length ? results.map(r => `<article class="result"><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.title || r.url)}</a><div class="url">${escapeHtml(r.url)}</div><div class="desc">${escapeHtml(r.description || "")}</div></article>`).join("") : (q ? '<p class="empty">No indexed results yet.</p>' : "");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sandstorm Search</title><link rel="stylesheet" href="/styles.css"></head><body><header><h1>Sandstorm</h1><p>Search pages indexed from Common Crawl · private by design</p></header><form class="search" method="get" action="/search"><input name="q" value="${escapeHtml(q)}" autofocus placeholder="Search the web..."><button>Search</button></form><main>${cards}</main><p class="netlify-note">Netlify edition · index generated from Sandstorm's Common Crawl index.</p></body></html>`;
}

export default async (req) => {
  const url = new URL(req.url);
  const rawQuery = url.searchParams.get("q") || "";
  if (rawQuery.length > MAX_QUERY) return json({ detail: "Query too long." }, 400);
  const q = rawQuery.trim();
  const rawLimit = url.searchParams.get("limit") || "10";
  const limit = Number(rawLimit);
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_RESULTS) {
    return json({ detail: "Invalid result limit." }, 400);
  }

  const data = await loadIndex();
  const terms = tokens(q);
  const results = q && terms.length
    ? data.pages
        .map(safePage)
        .filter(Boolean)
        .map(page => ({ page, score: score(page, terms) }))
        .filter(x => x.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, limit)
        .map(x => x.page)
    : [];

  if (url.pathname === "/api/search") return json({ query: q, results });
  return new Response(htmlPage(q, results), {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer"
    }
  });
};
