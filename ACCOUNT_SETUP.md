# Sandstorm Search — account storage setup

The account system no longer requires PostgreSQL or `DATABASE_URL`.

It now stores the account database as a **private SQLite database serialized inside Vercel Blob**. Vercel Blob is persistent storage, while SQLite remains the query engine used by `api/account.py`.

## Vercel setup

1. Open the Sandstorm Search project in Vercel.
2. Open **Storage**.
3. Create a **Blob** store.
4. Choose **Private** access.
5. Connect the store to this Vercel project.
6. Redeploy.

The connected Blob store supplies the credentials needed by the Vercel Python SDK. **No `DATABASE_URL` is required.**

## Security

The Blob store must be **Private**. Account data, sessions, pairing data, release-code hashes, and proof data are not intended to be public.

The secret phrase itself is never sent to the server.

## Note

The account database is serialized to Blob on each account operation. This avoids requiring PostgreSQL, but a relational database is still preferable for very high traffic because it provides stronger concurrent-write guarantees.

## Proof uploads

The account endpoint accepts proof uploads up to 4 MB because Vercel Functions impose a request-body limit. The proof itself is stored in the private Blob store.

