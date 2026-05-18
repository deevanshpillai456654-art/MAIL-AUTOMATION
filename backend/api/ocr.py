"""OCR Engine API for documents, emails, text extraction, and structured fields.

Endpoints:
  POST /ocr/scan           - upload a file and extract text + fields
  POST /ocr/scan-email     - extract text from an email body/attachments by email ID
  GET  /ocr/history        - list past scan jobs
  GET  /ocr/result/{id}    - fetch a specific scan result
  DELETE /ocr/history/{id} - delete a history record
  DELETE /ocr/history      - clear all history
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

router = APIRouter(prefix="/ocr", tags=["ocr"])

_DB_PATH = str(Path(DATA_DIR) / "ocr_history.db")


# DB helpers

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS ocr_jobs (
            id          TEXT PRIMARY KEY,
            filename    TEXT,
            file_type   TEXT,
            mode        TEXT,
            raw_text    TEXT,
            fields_json TEXT,
            page_count  INTEGER DEFAULT 1,
            word_count  INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'done',
            error       TEXT,
            created_at  TEXT
        )
    """)
    con.commit()
    return con


# Field extraction

_PATTERNS: dict[str, str] = {
    "invoice_number": r"(?:invoice|inv|bill|reference)[\s#.:]*([A-Z0-9][A-Z0-9\-/]{2,20})",
    "po_number":      r"(?:purchase\s*order|P\.?O\.?|order\s*no)[\s#.:]*([A-Z0-9][A-Z0-9\-/]{2,20})",
    "date":           r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    "due_date":       r"(?:due\s+date|payment\s+due|due\s+by)[\s:]*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})",
    "total_amount":   r"(?:total|grand\s+total|amount\s+due|balance\s+due)[\s:$\u20ac\u00a3\u00a5]*([0-9]{1,3}(?:[,\s][0-9]{3})*(?:\.[0-9]{1,2})?)",
    "subtotal":       r"(?:subtotal|sub\s*total)[\s:$\u20ac\u00a3\u00a5]*([0-9]{1,3}(?:[,\s][0-9]{3})*(?:\.[0-9]{1,2})?)",
    "tax":            r"(?:tax|vat|gst|hst)[\s:$\u20ac\u00a3\u00a5]*([0-9]{1,3}(?:[,\s][0-9]{3})*(?:\.[0-9]{1,2})?)",
    "currency":       r"\b(USD|EUR|GBP|INR|AUD|CAD|JPY|CNY|CHF|SGD)\b",
    "email":          r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
    "phone":          r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{4}",
    "vendor_name":    r"(?:from|vendor|supplier|seller|company|issued\s+by)[\s:]+([A-Z][A-Za-z0-9\s&,\.]{2,50}?)(?:\n|,|\.|LLC|Ltd|Inc|Corp|GmbH)",
    "tracking_number":r"(?:tracking|shipment|waybill|AWB|HAWB)[\s#:]*([A-Z0-9]{8,30})",
    "gstin":          r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b",
    "pan":            r"\b([A-Z]{5}\d{4}[A-Z])\b",
}

_CONTRACT_PATTERNS: dict[str, str] = {
    "parties":        r"(?:between|party|parties)[\s:]+([A-Z][^\n]{5,80})",
    "effective_date": r"(?:effective|commencement|start)\s+date[\s:]+([^\n]{5,40})",
    "term":           r"(?:term|duration|period)[\s:]+([^\n]{5,60})",
    "governing_law":  r"(?:governing\s+law|jurisdiction)[\s:]+([^\n]{5,60})",
}


def _extract_fields(text: str, mode: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    patterns = dict(_PATTERNS)
    if mode == "contract":
        patterns.update(_CONTRACT_PATTERNS)

    for key, pattern in patterns.items():
        try:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                fields[key] = m.group(1).strip() if m.lastindex else m.group(0).strip()
        except re.error:
            pass

    # Auto-detect document type
    text_lower = text.lower()
    if mode == "auto":
        if any(w in text_lower for w in ("invoice", "bill to", "amount due")):
            fields["_detected_type"] = "invoice"
        elif any(w in text_lower for w in ("receipt", "thank you for your purchase", "order total")):
            fields["_detected_type"] = "receipt"
        elif any(w in text_lower for w in ("agreement", "contract", "whereas", "hereinafter")):
            fields["_detected_type"] = "contract"
        elif any(w in text_lower for w in ("purchase order", "p.o. number", "vendor")):
            fields["_detected_type"] = "purchase_order"
        else:
            fields["_detected_type"] = "document"

    return fields


# Text extractors

class _StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _extract_pdf(data: bytes) -> tuple[str, int]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=data, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages), len(pages)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF extraction failed: {exc}") from exc


def _extract_image(_data: bytes, filename: str) -> tuple[str, int]:
    return (
        f"[Image file: {filename}]\n"
        "Full pixel-level OCR requires a system Tesseract installation.\n"
        "Text-based content (if embedded) was not found in this image.\n"
        "Tip: Convert image to PDF first for best results.",
        1,
    )


def _extract_text(data: bytes) -> tuple[str, int]:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc), 1
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), 1


def _extract_eml(data: bytes) -> tuple[str, int]:
    import email as _email
    msg = _email.message_from_bytes(data)
    parts: list[str] = []
    subject = msg.get("Subject", "")
    sender  = msg.get("From", "")
    date    = msg.get("Date", "")
    if subject: parts.append(f"Subject: {subject}")
    if sender:  parts.append(f"From: {sender}")
    if date:    parts.append(f"Date: {date}")
    parts.append("")
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain":
            pl = part.get_payload(decode=True)
            if pl:
                parts.append(pl.decode("utf-8", errors="replace"))
        elif ct == "text/html":
            pl = part.get_payload(decode=True)
            if pl:
                parser = _StripHTML()
                parser.feed(pl.decode("utf-8", errors="replace"))
                parts.append(parser.get_text())
    return "\n".join(parts), 1


def _do_extract(data: bytes, filename: str, content_type: str) -> tuple[str, int]:
    fn_lower = filename.lower()
    if fn_lower.endswith(".pdf") or content_type == "application/pdf":
        return _extract_pdf(data)
    if fn_lower.endswith(".eml") or content_type in ("message/rfc822",):
        return _extract_eml(data)
    if any(fn_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp")):
        return _extract_image(data, filename)
    return _extract_text(data)


def _save_job(
    filename: str,
    file_type: str,
    mode: str,
    raw_text: str,
    fields: dict[str, Any],
    page_count: int,
    error: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    word_count = len(raw_text.split()) if raw_text else 0
    con = _db()
    con.execute(
        """INSERT INTO ocr_jobs
           (id, filename, file_type, mode, raw_text, fields_json,
            page_count, word_count, status, error, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, filename, file_type, mode, raw_text,
            json.dumps(fields, ensure_ascii=False),
            page_count, word_count,
            "error" if error else "done",
            error,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    con.commit()
    con.close()
    return job_id


# Endpoints

@router.post("/scan", summary="Scan an uploaded document")
async def scan_document(
    file: UploadFile = File(...),
    mode: str = Form("auto"),
    _auth=Depends(require_local_auth),
):
    if mode not in ("auto", "invoice", "receipt", "contract", "raw"):
        mode = "auto"

    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    filename    = file.filename or "document"
    content_type = file.content_type or ""

    raw_text, page_count = _do_extract(data, filename, content_type)
    fields = {} if mode == "raw" else _extract_fields(raw_text, mode)
    job_id = _save_job(filename, content_type, mode, raw_text, fields, page_count)

    try:
        from backend.api.event_bus import emit as _emit
        asyncio.create_task(_emit(
            "ocr.completed",
            source="ocr_engine",
            payload={
                "job_id": job_id,
                "filename": filename,
                "mode": mode,
                "page_count": page_count,
                "word_count": len(raw_text.split()),
                "fields_extracted": len(fields),
            },
            severity="low",
        ))
    except Exception:
        pass

    return {
        "job_id":     job_id,
        "filename":   filename,
        "mode":       mode,
        "page_count": page_count,
        "word_count": len(raw_text.split()),
        "raw_text":   raw_text[:20000],
        "fields":     fields,
    }


@router.post("/scan-email", summary="Extract text from an email")
async def scan_email(
    body: dict,
    _auth=Depends(require_local_auth),
):
    """
    Accepts either:
      { subject, sender, body_text, body_html } - inline content from frontend
      { email_id }                              - DB lookup fallback
    """
    parts: list[str] = []

    # Prefer inline content passed directly from the frontend
    subject  = body.get("subject", "")
    sender   = body.get("sender", "")
    body_txt = body.get("body_text", "")
    body_htm = body.get("body_html", "")

    if subject:  parts.append(f"Subject: {subject}")
    if sender:   parts.append(f"From: {sender}")
    parts.append("")

    if body_txt:
        parts.append(body_txt)
    elif body_htm:
        p = _StripHTML()
        p.feed(body_htm)
        parts.append(p.get_text())
    else:
        # Fallback: try DB lookup by email_id
        email_id = body.get("email_id")
        if email_id:
            try:
                import sqlite3 as _sq
                db_path = str(Path(DATA_DIR) / "emails.db")
                con = _sq.connect(db_path)
                con.row_factory = _sq.Row
                row = con.execute(
                    "SELECT * FROM emails WHERE id = ?", (str(email_id),)
                ).fetchone()
                con.close()
                if row:
                    r = dict(row)
                    if not subject:
                        subject = r.get("subject", f"Email {email_id}")
                        parts[0] = f"Subject: {subject}"
                    if r.get("body_text"):
                        parts.append(r["body_text"])
                    elif r.get("body_html"):
                        p = _StripHTML()
                        p.feed(r["body_html"])
                        parts.append(p.get_text())
            except Exception:
                pass

    if not any(p.strip() for p in parts if not p.startswith(("Subject:", "From:"))):
        parts.append("[No readable content found in this email]")

    raw_text = "\n".join(parts)
    fields = _extract_fields(raw_text, "auto")
    filename = subject or "Email scan"
    job_id = _save_job(filename, "email", "auto", raw_text, fields, 1)

    try:
        from backend.api.event_bus import emit as _emit
        asyncio.create_task(_emit(
            "ocr.completed",
            source="ocr_engine",
            payload={
                "job_id": job_id,
                "filename": filename,
                "mode": "auto",
                "source_type": "email",
                "word_count": len(raw_text.split()),
                "fields_extracted": len(fields),
            },
            severity="low",
        ))
    except Exception:
        pass

    return {
        "job_id":     job_id,
        "filename":   filename,
        "mode":       "auto",
        "page_count": 1,
        "word_count": len(raw_text.split()),
        "raw_text":   raw_text[:20000],
        "fields":     fields,
    }


@router.get("/history", summary="List OCR scan history")
async def get_history(
    limit: int = 50,
    _auth=Depends(require_local_auth),
):
    con = _db()
    rows = con.execute(
        "SELECT id, filename, file_type, mode, page_count, word_count, status, error, created_at "
        "FROM ocr_jobs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    return {"jobs": [dict(r) for r in rows]}


@router.get("/result/{job_id}", summary="Get a specific OCR result")
async def get_result(
    job_id: str,
    _auth=Depends(require_local_auth),
):
    con = _db()
    row = con.execute("SELECT * FROM ocr_jobs WHERE id = ?", (job_id,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    result = dict(row)
    try:
        result["fields"] = json.loads(result.get("fields_json") or "{}")
    except json.JSONDecodeError:
        result["fields"] = {}
    return result


@router.delete("/history/{job_id}", summary="Delete a history record")
async def delete_result(
    job_id: str,
    _auth=Depends(require_local_auth),
):
    con = _db()
    con.execute("DELETE FROM ocr_jobs WHERE id = ?", (job_id,))
    con.commit()
    con.close()
    return {"message": "Deleted"}


@router.delete("/history", summary="Clear all OCR history")
async def clear_history(_auth=Depends(require_local_auth)):
    con = _db()
    con.execute("DELETE FROM ocr_jobs")
    con.commit()
    con.close()
    return {"message": "History cleared"}
