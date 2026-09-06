import { getStore } from "@netlify/blobs";
import { createHash } from "node:crypto";

const store = getStore("sandstorm-private");
const MAX_BLOB = 20_000_000;

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store" } });
}

function idFor(blob) {
  return createHash("sha256").update(blob, "ascii").digest("hex");
}

export default async (req) => {
  const method = req.method.toUpperCase();
  if (method === "POST") {
    const body = await req.json().catch(() => null);
    const blob = body?.blob;
    if (typeof blob !== "string" || !blob || blob.length > MAX_BLOB || !/^[A-Za-z0-9_-]+$/.test(blob)) {
      return json({ detail: "Invalid ciphertext" }, 400);
    }
    const id = idFor(blob);
    await store.set(id, blob, { onlyIfNew: true });
    return json({ id });
  }

  if (method === "GET") {
    const { blobs } = await store.list();
    const results = [];
    for (const item of blobs.slice(0, 5000)) {
      const blob = await store.get(item.key);
      if (typeof blob === "string") results.push({ id: item.key, blob });
    }
    return json({ results });
  }

  return json({ detail: "Method not allowed" }, 405);
};
