import { getStore } from "@netlify/blobs";
import { createHash } from "node:crypto";

const store = getStore("sandstorm-private");
const MAX_BLOB = 4_000_000;
const MAX_PAGE = 100;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{43}$/;
const CIPHERTEXT_RE = /^[A-Za-z0-9_-]+$/;
const KEY_RE = /^[a-f0-9]{64}$/;

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "content-security-policy": "default-src 'none'; frame-ancestors 'none'"
    }
  });
}

function hashCapability(capability) {
  return createHash("sha256").update(capability, "ascii").digest("hex");
}

function idFor(blob) {
  return createHash("sha256").update(blob, "ascii").digest("hex");
}

function getCapability(req) {
  const value = req.headers.get("x-private-capability");
  return typeof value === "string" && CAPABILITY_RE.test(value) ? value : null;
}

function pagination(req) {
  const params = new URL(req.url).searchParams;
  const rawLimit = params.get("limit");
  const rawCursor = params.get("cursor");
  const limit = rawLimit === null ? MAX_PAGE : Number(rawLimit);
  const cursor = rawCursor === null || rawCursor === "" ? "" : rawCursor;

  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PAGE) return null;
  if (cursor && !KEY_RE.test(cursor)) return null;
  return { limit, cursor };
}

export default async (req) => {
  const method = req.method.toUpperCase();
  const capability = getCapability(req);

  if (!capability) return json({ detail: "A valid private capability is required." }, 401);
  if (method !== "GET" && method !== "POST") return json({ detail: "Method not allowed" }, 405);

  const capabilityHash = hashCapability(capability);
  const prefix = `${capabilityHash}/`;

  if (method === "POST") {
    const contentType = req.headers.get("content-type") || "";
    if (!contentType.toLowerCase().startsWith("application/json")) {
      return json({ detail: "JSON is required." }, 415);
    }

    const contentLength = Number(req.headers.get("content-length") || "0");
    if (Number.isFinite(contentLength) && contentLength > MAX_BLOB + 2048) {
      return json({ detail: "Request too large." }, 413);
    }

    const body = await req.json().catch(() => null);
    const blob = body?.blob;
    if (typeof blob !== "string" || blob.length === 0 || blob.length > MAX_BLOB || !CIPHERTEXT_RE.test(blob)) {
      return json({ detail: "Invalid ciphertext" }, 400);
    }

    const id = idFor(blob);
    await store.set(`${prefix}${id}`, blob, { onlyIfNew: true });
    return json({ id });
  }

  const page = pagination(req);
  if (!page) return json({ detail: "Invalid pagination parameters." }, 400);

  const listing = await store.list({ prefix, cursor: page.cursor, limit: page.limit });
  const results = [];

  for (const item of listing.blobs) {
    const blob = await store.get(item.key);
    if (typeof blob === "string" && blob.length <= MAX_BLOB && CIPHERTEXT_RE.test(blob)) {
      results.push({ id: item.key.slice(prefix.length), blob });
    }
  }

  return json({
    results,
    cursor: listing.cursor || null,
    hasMore: Boolean(listing.cursor)
  });
};
