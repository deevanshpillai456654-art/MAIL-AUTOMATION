# AI Email Organizer for Edge

This is the edge packaging target for the universal AI Email Organizer browser extension runtime.

Security model:
- The extension never stores OAuth access tokens, refresh tokens, provider passwords, or API secrets.
- Runtime messages are nonce-validated and payload-size limited by `secure_message_bridge.js`.
- Mailbox authority remains with the backend/local service.
- Content scripts are render-only overlays with local-service API mediation through the background worker.

Build note: package this folder with the target browser store tooling. Safari still requires Apple's Safari Web Extension wrapper/signing step outside this repository.
