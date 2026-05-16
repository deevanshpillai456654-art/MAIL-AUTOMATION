# iOS Security Model

- Store local cache keys in Keychain/Secure Enclave where available.
- Store no provider access tokens, refresh tokens, client secrets, or passwords.
- Use universal links / registered callback schemes only for OAuth continuation.
- Treat push notifications as metadata hints; never include email bodies or secrets.
- Scope local cache by tenant/account/provider/mailbox.
