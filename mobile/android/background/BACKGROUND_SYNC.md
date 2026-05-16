# Android Background Sync Contract

Background sync must be server-authorized, replay-safe, and queue-limited. The Android service may request a sync window but the backend owns mailbox authority, replay ACKs, and provider throttling. Delayed retries must use exponential backoff and must not wake-loop on provider outages.
