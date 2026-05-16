# iOS Client Foundation

This folder contains the production architecture contract for the iOS mailbox client. iOS is a zero-trust client: it renders server-authorized mailbox state, uses replay-safe sync checkpoints, and stores no plaintext OAuth or provider credentials.

Native App Store signing, APNs credentials, Keychain access group validation, and background-fetch hardware tests require the real iOS build environment.
