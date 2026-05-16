# Authentication Documentation

## OAuth 2.0 Flow

### Gmail OAuth

1. Redirect to Google OAuth:
```
https://accounts.google.com/o/oauth2/v2/auth
?client_id=CLIENT_ID
&redirect_uri=http://127.0.0.1:4597/auth/gmail/callback
&response_type=code
&scope=https://mail.google.com/ https://www.googleapis.com/auth/gmail.readonly
&access_type=offline
```

2. Receive authorization code
3. Exchange for tokens:
```
POST https://oauth2.googleapis.com/token
```

4. Store encrypted tokens

### Outlook OAuth

1. Redirect to Microsoft:
```
https://login.microsoftonline.com/common/oauth2/v2.0/authorize
```

2. Exchange code for tokens
3. Store tokens securely

### Token Refresh

Tokens automatically refreshed before expiry:
```python
async def refresh_token(self, provider: str) -> str:
    if token_expiry - now < 300:  # 5 min buffer
        new_token = await get_new_token(refresh_token)
        await store_encrypted(new_token)
    return current_token
```

## IMAP Authentication

For non-OAuth providers (Proton, Generic):
- Username/password stored encrypted
- App-specific passwords supported (iCloud)
- 2FA with app-specific password

## Localhost Callbacks

OAuth callbacks handled locally:
```
http://127.0.0.1:4597/auth/{provider}/callback
```

Security:
- CSRF token validation
- State parameter verification
- Redirect URI validation

## Reconnect Flow

1. Detect token expiry/failure
2. Check refresh token validity
3. Attempt token refresh
4. On failure, prompt re-auth
5. Update stored tokens

---

*For providers, see `docs/providers/README.md`*