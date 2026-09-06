import { readFile } from "node:fs/promises";

let indexPromise;
async function loadIndex() {
  if (!indexPromise) {
    indexPromise = readFile(new URL("../../public/index.json", import.meta.url), "utf8")
      .then(JSON.parse)
      .catch(() => ({ pages: [] }));
  }
  return indexPromise;
}

function tokens(q) {
  return q.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
}

function score(page, terms) {
  const title = page.title.toLocaleLowerCase();
  const description = page.description.toLocaleLowerCase();
  const content = page.content.toLocaleLowerCase();
  let s = 0;
  for (const term of terms) {
    if (title.includes(term)) s += 12;
    if (description.includes(term)) s += 5;
    if (content.includes(term)) s += 1;
    if (page.url.toLocaleLowerCase().includes(term)) s += 2;
  }
  return s;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function htmlPage(q, results) {
  const cards = results.length ? results.map(r => `<article class="result"><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title || r.url)}</a><div class="url">${escapeHtml(r.url)}</div><div class="desc">${escapeHtml(r.description || "")}</div></article>`).join("") : (q ? '<p class="empty">No indexed results yet.</p>' : "");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sandstorm Search</title><link rel="stylesheet" href="/styles.css"></head><body><header><h1>Sandstorm</h1><p>Search pages indexed from Common Crawl · private by design</p></header><form class="search" method="get" action="/search"><input name="q" value="${escapeHtml(q)}" autofocus placeholder="Search the web..."><button>Search</button></form><main>${cards}</main><p class="netlify-note">Netlify edition · index generated from Sandstorm's Common Crawl index.</p></body></html>`;
}

export default async (req) => {
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") || "").slice(0, 300).trim();
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 10), 1), 50);
  const data = await loadIndex();
  const terms = tokens(q);
  const results = q ? data.pages.map(page => ({ page, score: score(page, terms) })).filter(x => x.score > 0).sort((a,b) => b.score - a.score).slice(0, limit).map(x => x.page) : [];

  if (url.pathname === "/api/search") {
    return Response.json({ query: q, results });
  }
  return new Response(htmlPage(q, results), { headers: { "content-type": "text/html; charset=utf-8" } });
};
