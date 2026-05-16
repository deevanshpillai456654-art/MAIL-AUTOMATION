# UI State Contract

Frontend state is mailbox-scoped and server-authoritative. Every state event must include tenant/account/provider/mailbox scope, event ID, and monotonic sequence where available. Duplicate event IDs and stale sequences are ignored by client stores.
