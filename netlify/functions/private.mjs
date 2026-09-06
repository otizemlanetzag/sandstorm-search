import { getStore } from "@netlify/blobs";
import { createHash } from "node:crypto";

const store = getStore("sandstorm-private");
const MAX_BLOB = 20_000_000;
const MAX_RESULTS = 5000;
const CAPABILITY_RE = /^[A-Za-z0-9_-]{43}$/;
const CIPHERTEXT_RE = /^[A-Za-z0-9_-]+$/;

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
  // 32 random bytes encoded as unpadded base64url are exactly 43 characters.
  return typeof value === "string" && CAPABILITY_RE.test(value) ? value : null;
}

export default async (req) => {
  const method = req.method.toUpperCase();
  const capability = getCapability(req);

  if (!capability) {
    return json({ detail: "A valid private capability is required." }, 401);
  }

  if (method !== "GET" && method !== "POST") {
    return json({ detail: "Method not allowed" }, 405);
  }

  const capabilityHash = hashCapability(capability);
  const prefix = `${capabilityHash}/`;

  if (method === "POST") {
    const contentType = req.headers.get("content-type") || "";
    if (!contentType.toLowerCase().startsWith("application/json")) {
      return json({ detail: "JSON is required." }, 415);
    }

    const body = await req.json().catch(() => null);
    const blob = body?.blob;

    if (
      typeof blob !== "string" ||
      blob.length === 0 ||
      blob.length > MAX_BLOB ||
      !CIPHERTEXT_RE.test(blob)
    ) {
      return json({ detail: "Invalid ciphertext" }, 400);
    }

    const id = idFor(blob);
    const key = `${prefix}${id}`;
    await store.set(key, blob, { onlyIfNew: true });
    return json({ id });
  }

  // GET is always scoped to the caller's capability namespace. There is no
  // application-level operation that lists the complete private store.
  const { blobs } = await store.list({ prefix });
  const results = [];

  for (const item of blobs.slice(0, MAX_RESULTS)) {
    const blob = await store.get(item.key);
    if (typeof blob === "string" && CIPHERTEXT_RE.test(blob) && blob.length <= MAX_BLOB) {
      results.push({ id: item.key.slice(prefix.length), blob });
    }
  }

  return json({ results });
};
