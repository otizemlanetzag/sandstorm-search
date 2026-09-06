# Security model

Sandstorm follows a **security-by-design** model. Security does not depend on
hidden endpoints, secret source code, obscure identifiers, or keeping the
implementation private. The repository is public by design.

## Threat model

We assume an attacker can:

- Read all client and server source code.
- Discover all public HTTP endpoints and their documented behavior.
- Submit arbitrary requests and malformed input to public endpoints.
- Obtain ciphertext stored by the private-data service.
- Observe public metadata such as blob identifiers and response sizes.

The private-data design is intended to prevent an attacker who has only server
access from decrypting private notes or crossing one client's private-blob
namespace into another client's namespace.

This does **not** protect a device that is already compromised, a browser page
that has been modified by an attacker, or a private capability that the user
voluntarily discloses. End-to-end encryption cannot make a compromised client
trustworthy.

## End-to-end encryption

Sandstorm's private-data path uses two separate client-held secrets:

1. A random AES-256-GCM encryption key. The server never receives it.
2. A separate random 256-bit capability used only for authorization to the
   client's private blob namespace.

The encryption key and capability are generated independently. Neither is
committed to Git, placed in a URL, or sent to the server in plaintext as
persistent data.

Ciphertexts are encrypted in the browser before upload. The server stores only
ciphertext and a SHA-256 hash of the capability as part of the storage
namespace. The raw capability is not stored by the server.

### Capability isolation

Private blob requests require the `X-Private-Capability` header. The server
hashes the capability and uses the resulting value as a namespace prefix.
There is no unscoped private-blob listing endpoint.

Knowing a ciphertext ID, knowing the complete source code, or enumerating the
storage API does not provide authorization to retrieve another capability's
blobs through the application endpoint.

The capability is intentionally separate from the AES key. Compromise of one
secret must not automatically reveal the other.

## Cryptography

The reference client implementation uses the Web Crypto API with AES-256-GCM
and fresh random 96-bit nonces for each encryption operation.

The server-side `backend/e2e_crypto.py` implementation also uses AES-256-GCM
with random 96-bit nonces and authenticated encryption. It performs no network
access.

Do not reuse a nonce with the same AES-GCM key.

## Important limitation

The public Common Crawl search index cannot be made fully end-to-end encrypted
while retaining ordinary server-side full-text search: the server must be able
to inspect searchable plaintext or use a specialized searchable-encryption
protocol. Therefore E2E encryption protects private/user data, not the public
Common Crawl corpus itself.

## Transport security

Production deployments must use HTTPS/TLS. Netlify provides TLS for the
public deployment; any self-hosted deployment must configure TLS appropriately.

TLS protects the capability and ciphertext while they are in transit. It does
not replace application-level authorization or client-side encryption.

## Input and output handling

- Client input is untrusted.
- Ciphertexts are restricted to the expected base64url representation and a
  maximum size.
- Private search results are rendered with HTML escaping rather than treating
  decrypted note contents as markup.
- The private endpoint returns `Cache-Control: no-store` and
  `X-Content-Type-Options: nosniff`.
- The server must not log encryption keys or raw capabilities.

## Key handling

- Never commit encryption keys or capabilities to Git.
- Never put keys or capabilities in URLs.
- Never derive the capability from the AES encryption key.
- Losing the only client-side AES key means encrypted data cannot be recovered.
- The server-side `SANDSTORM_ENCRYPTION_KEY`, where used by backend tooling, is
  intentionally separate from the client-side E2E key and must not be treated
  as a recovery key.

## No security by obscurity

A security claim is considered invalid if it relies on an attacker not knowing
how Sandstorm works. Attackers are assumed to be able to read this repository.
The system therefore relies on cryptographic verification, explicit
authorization, input validation, and standard browser/server security
boundaries rather than hidden implementation details.

## Reporting

Please report suspected security vulnerabilities privately to the repository
maintainer before publicly disclosing an exploitable issue, when practical.
