# Gap-Focused Platform Build — v11 Clean

This build removes the old in-app ERP/CRM/full-module direction and keeps only a platform layer under `/platform`.

## What changed

- No existing MailPilot/AI36 core files were modified.
- All new work is isolated under `/platform`.
- The system remains a logistics operations connector platform.
- It does not become ERP, CRM, accounting, HRMS, payroll, inventory ERP, TMS, or WMS.

## Included platform areas

1. Plugin runtime and connector SDK
2. Unified shipment workspace
3. Local WhatsApp operations engine
4. Approval-first automation layer
5. OCR pipeline and document intelligence
6. Event normalization engine
7. Tracking aggregation system
8. Email + WhatsApp unified communication model
9. Enterprise queue and worker system
10. Tenant isolation architecture
11. Operational dashboard assets
12. Search/indexing layer
13. Offline-first queue preparation
14. Security and governance helpers

## Integration rule

The optional router is included but not mounted. Mounting must be done manually by the existing app when approved.
