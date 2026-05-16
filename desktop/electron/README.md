# Desktop Runtime Security

This Electron shell is intentionally thin and zero-trust. It loads the locally served dashboard, keeps `nodeIntegration` disabled, enables `contextIsolation` and `sandbox`, and exposes only two validated IPC methods through the preload bridge.

The renderer never receives provider passwords, OAuth refresh tokens, or mailbox authority. All mailbox actions must go through the local API and backend authorization checks.
