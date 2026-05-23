# Browser extensions

The six per-browser folders (chrome, edge, brave, firefox, opera, safari) ship
the same INTEMO extension with per-browser manifest tweaks only. `chrome/` is
the **canonical** source. Edit there, then propagate.

## Layout

```
extensions/
├── chrome/      ← canonical source for all shared files
├── edge/
├── brave/
├── firefox/
├── opera/
├── safari/
├── security/    ← backend-side extension runtime guard (Python)
└── README.md    ← (this file)
```

## What's shared vs. per-browser

| File | Source of truth |
|---|---|
| `background.js`             | `chrome/` (synced) |
| `content.js`                | `chrome/` (synced) |
| `extension_runtime.js`      | `chrome/` (synced) |
| `options.html`              | `chrome/` (synced) |
| `options.js`                | `chrome/` (synced) |
| `popup.html`                | `chrome/` (synced) |
| `popup.js`                  | `chrome/` (synced) |
| `secure_message_bridge.js`  | `chrome/` (synced) |
| `ui.css`                    | `chrome/` (synced) |
| `manifest.json`             | **per-browser** (description / gecko block / etc.) |
| `README.md`                 | **per-browser** (browser-specific install notes) |
| `integrity.json`            | **per-browser** (auto-generated hashes) |
| `icon*.png`                 | per-browser (currently identical but kept separate) |

## Sync workflow

After editing any shared file in `chrome/`, propagate to the other 5:

```bash
python scripts/sync_browser_extensions.py
```

To verify the folders are in sync (CI gate / pre-commit):

```bash
python scripts/sync_browser_extensions.py --check
```

`--check` exits with code 1 (and prints which files drift) when any of the
other 5 folders disagrees with `chrome/` on a shared file.

## Packaging

`scripts/package_browser_extensions.py` builds the per-browser `.zip` /
`.crx` / `.xpi` artifacts from these source folders into
`browser-extension-packages/`.

## Why not generate the other 5 at build time?

Build-time generation is the natural next step, but it requires updating
`scripts/{build,full_build,package_browser_extensions,prepare_installer_payload}.py`
and several tests that walk the per-browser folders directly. Until that
coordinated refactor lands, the sync script is the lower-risk way to keep
the folders aligned.
