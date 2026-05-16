# MailPilot Platform-Only Logistics Operations Layer

This clean build keeps the original MailPilot/AI36 application untouched and adds new work only under `/platform`.

It is intentionally **not** an ERP, CRM, accounting, HRMS, inventory ERP, full TMS, or WMS. It is a logistics operations workspace layer for:

- plugin runtime and connector SDK
- shipment workspaces
- local WhatsApp operations orchestration
- approval-first automation
- OCR/document intelligence pipeline
- event normalization and tracking aggregation
- unified email + WhatsApp communication timelines
- tenant-aware queues/workers
- security/governance helpers
- search/indexing foundation
- offline-first preparation

The root `/platform` folder does not include `__init__.py` to avoid shadowing Python's standard-library `platform` module.
## v12 Package Note

This ZIP intentionally contains only the `/platform` folder. Original MailPilot/AI36 application files were removed from this package so it can be used as a clean isolated platform layer.

