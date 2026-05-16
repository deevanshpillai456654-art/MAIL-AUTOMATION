# Android Security Model

- Use Android Keystore-backed encryption for local cache keys.
- Store no provider OAuth access tokens, refresh tokens, client secrets, or mailbox passwords.
- Sign every client runtime request with backend-issued short-lived session material.
- Treat push notifications as hints only; fetch details after authenticated API validation.
- Scope cache keys by tenant, account, provider, and mailbox.
