# Platform-Only v12 Cleanup Report

This package removes the original MailPilot/AI36 app files from the ZIP and keeps only the isolated `/platform` logistics operations layer.

## Kept

```text
/platform
```

## Removed from this package

```text
Original MailPilot/AI36 app root files
backend/
frontend/
extensions/
updater/
installer/
outlook-addin/
gmail-extension/
mobile/
clients/
recovery/
logs/
old generated ERP/CRM/accounting/tracking plugin builds
old generated enterprise overlays
```

## Purpose

This is only the platform layer requested for gap-focused logistics operations infrastructure: plugin runtime, connector SDK, shipment workspace, WhatsApp operations, approval-first automation, OCR pipeline, event normalization, tracking aggregation, unified communication, queues/workers, tenant isolation, search/indexing, and security/governance.

## Core app modification status

```text
Original app files included: no
Original app files modified: no
Only /platform included: yes
```

## Native-only status

```text
.ts files: 0
.tsx files: 0
.txs files: 0
```
