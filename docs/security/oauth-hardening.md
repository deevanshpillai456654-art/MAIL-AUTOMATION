# OAuth Hardening

## Overview

This document describes OAuth hardening measures for security.

## Hardening Features

| Feature | Implementation |
|---------|---------------|
| PKCE | Required for all flows |
| Nonce | Validate state parameter |
| Replay prevention | One-time code |
| Token rotation | Auto-refresh before expiry |

## PKCE Implementation

```python
class OAuthHardener:
    def generate_pkce(self) -> tuple[str, str]:
        verifier = secrets.token_urlsafe(32)
        challenge = hashlib.sha256(verifier.encode()).digest()
        return verifier, challenge
```

## Security Checks

```yaml
oauth:
  pkce_required: true
  nonce_required: true
  max_age: 3600
  refresh_before: 300
```

## Related Documentation

- [Overview](overview.md)
- [Token Vault](token-vault.md)