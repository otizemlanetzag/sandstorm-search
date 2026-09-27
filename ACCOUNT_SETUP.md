# Cross-device Sandstorm accounts

Sandstorm accounts are identified only by the user's secret phrase. The phrase itself is never stored in PostgreSQL.

## Server setup

The account API uses PostgreSQL through the `DATABASE_URL` environment variable.

1. Create a PostgreSQL database with any trusted PostgreSQL provider.
2. Copy its connection string.
3. Add this environment variable to the deployment:

```
DATABASE_URL=postgresql://...
```

4. Redeploy Sandstorm.

The API creates these tables automatically on first account request:

- `sandstorm_accounts`
- `sandstorm_sessions`

No manual SQL migration is required.

## How the account works

- The browser derives a stable SHA-256 account identifier from the secret phrase.
- A per-account PBKDF2 salt is used to derive the authentication proof.
- Only the derived identifier, salts, and a server-side verifier are stored.
- The raw secret phrase is never sent to the server and is never stored.
- After login, the server gives the browser an HttpOnly, Secure, SameSite session cookie.
- Settings are stored in PostgreSQL, so the same secret phrase can log in from another computer.
- Logging out removes the server session.
- The secret phrase remains the only user-provided identifying information.

## Important

This replaces the previous browser-only `localStorage` account system. Existing local-only accounts cannot automatically be migrated because the server never received their secret phrase. On the first use of the new system, create the account again with the same secret phrase.

Use HTTPS in production so the Secure session cookie works correctly.
