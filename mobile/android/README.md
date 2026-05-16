# Android Client Foundation

This folder contains the production-ready architecture contract for the Android mailbox client. The native app must remain a zero-trust renderer: it never stores plaintext OAuth tokens, refresh tokens, provider passwords, or mailbox authority. OAuth credentials stay in the backend/vault and Android stores only device-local encrypted UI cache and server-issued short-lived session material.

Implemented repository support:
- Android package structure and manifest template.
- Background sync contract.
- Secure notification and widget contract.
- Mobile crash/runtime telemetry modules under `mobile/telemetry`.
- Cross-platform sync governance under `clients/sync`.

Native build signing, Play Store packaging, FCM production credentials, and biometric hardware tests require the real Android build environment.
