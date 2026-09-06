import { getStore } from "@netlify/blobs";
import { createHash } from "node:crypto";

const store = getStore("sandstorm-private");
const MAX_BLOB = 20_000_000;
const CAPABILITY_BYTES = 32;
const MAX_RESULTS = 5000;

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
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
  // 32 random bytes encoded as unpadded base64url are 43 characters.
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value)) return null;
  return value;
}

export default async (req) => {
  const method = req.method.toUpperCase();
  const capability = getCapability(req);

  if (!capability) {
    return json({ detail: "A valid private capability is required." }, 401);
  }

  const capabilityHash = hashCapability(capability);
  const prefix = `${capabilityHash}/`;

  if (method === "POST") {
    const body = await req.json().catch(() => null);
    const blob = body?.blob;

    if (
      typeof blob !== "string" ||
      !blob ||
      blob.length > MAX_BLOB ||
      !/^[A-Za-z0-9_-]+$/.test(blob)
    ) {
      return json({ detail: "Invalid ciphertext" }, 400);
    }

    const id = idFor(blob);
    const key = `${prefix}${id}`;

    await store.set(key, blob, { onlyIfNew: true });
    return json({ id });
  }

  if (method === "GET") {
    // The capability hash is used as a server-side namespace. The raw
    // capability is never stored, and there is no unscoped list operation.
    const { blobs } = await store.list({ prefix });
    const results = [];

    for (const item of blobs.slice(0, MAX_RESULTS)) {
      const blob = await store.get(item.key);
      if (typeof blob === "string") {
        results.push({ id: item.key.slice(prefix.length), blob });
      }
    }

    return json({ results });
  }

  return json({ detail: "Method not allowed" }, 405);
};
