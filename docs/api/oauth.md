# OAuth API

## Overview

This document describes the OAuth authentication API endpoints.

## Base URL

```
http://127.0.0.1:4597/api/v1
```

## Endpoints

### Get OAuth URL

Get OAuth authorization URL for a provider.

```http
GET /api/v1/auth/{provider}/url
```

#### Response

```json
{
  "success": true,
  "data": {
    "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...",
    "state": "random_state_string",
    "code_verifier": "pkce_code_verifier"
  }
}
```

### OAuth Callback

Handle OAuth callback.

```http
GET /api/v1/auth/{provider}/callback
```

#### Query Parameters

| Parameter | Description |
|-----------|-------------|
| code | Authorization code |
| state | State parameter |
| error | Error code (if any) |

#### Response

```json
{
  "success": true,
  "data": {
    "account": {
      "id": 1,
      "email": "user@gmail.com",
      "provider": "gmail"
    }
  }
}
```

### Refresh Token

Refresh an expired token.

```http
POST /api/v1/auth/refresh
```

#### Request Body

```json
{
  "provider": "gmail",
  "email": "user@gmail.com"
}
```

#### Response

```json
{
  "success": true,
  "data": {
    "refreshed": true
  }
}
```

### Revoke Token

Revoke OAuth tokens.

```http
POST /api/v1/auth/revoke
```

#### Request Body

```json
{
  "provider": "gmail",
  "email": "user@gmail.com"
}
```

#### Response

```json
{
  "success": true,
  "data": {
    "revoked": true
  }
}
```

## Supported Providers

| Provider | Authorization Endpoint |
|----------|----------------------|
| gmail | https://accounts.google.com/o/oauth2/v2/auth |
| outlook | https://login.microsoftonline.com/common/oauth2/v2.0/authorize |
| yahoo | https://login.yahoo.com/oauth2/request_auth |
| zoho | https://accounts.zoho.com/oauth/v2/authorize |

## OAuth Scopes

### Gmail

```
https://mail.google.com/
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.readonly
```

### Outlook

```
Calendars.Read
Mail.Read
Mail.ReadWrite
User.Read
```

## PKCE Implementation

The system uses PKCE (Proof Key for Code Exchange) for improved security:

1. Generate code_verifier (43-128 characters)
2. Create code_challenge (SHA256 hash of verifier)
3. Include in authorization request
4. Verify in callback

## Related Documentation

- [Overview](overview.md)
- [Accounts API](accounts.md)
- [Security Documentation](../security/oauth-hardening.md)