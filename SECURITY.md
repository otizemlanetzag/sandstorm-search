# Security model

## End-to-end encryption

Sandstorm's private-data path is designed around client-side encryption.
The encryption key is generated and retained by the client. The server receives
ciphertext, not the key.

The reference implementation in `backend/e2e_crypto.py` uses AES-256-GCM with
random 96-bit nonces and authenticated encryption. The module performs no
network access.

### Important limitation

The public Common Crawl search index cannot be made fully end-to-end encrypted
while retaining ordinary server-side full-text search: the server must be able
to inspect searchable plaintext or use a specialized searchable-encryption
protocol. Therefore E2E encryption protects private/user data, not the public
Common Crawl corpus itself.

### Key handling

- Never commit encryption keys to Git.
- Never put keys in URLs or logs.
- Store the client key locally in protected storage.
- Losing the only client key means the encrypted data cannot be recovered.
- The server-side `SANDSTORM_ENCRYPTION_KEY` is intentionally separate from
  the client-side E2E key and must not be used as a recovery key.

### Transport security

Use `backend/server.py` with `SANDSTORM_TLS_CERT` and `SANDSTORM_TLS_KEY` in
production so client-to-server traffic is encrypted with TLS.
