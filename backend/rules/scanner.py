"""Mailbox-aware rule scanning helpers.

The scanner builds a bounded, normalized text document from message metadata,
body fields and safe attachment extraction snippets. It reads persisted
attachment text first, then extracts text from known local attachment paths
using passive parsers only. It never executes macros or embedded scripts.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Use defusedxml to prevent XXE / billion-laughs on untrusted attachment XML.
from defusedxml import ElementTree

MAX_SOURCE_CHARS = 50000
MAX_PREVIEW_CHARS = 160
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".log", ".json", ".xml", ".html", ".htm", ".eml"}


def _parse_jsonish(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return fallback


def strip_html(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:MAX_SOURCE_CHARS]


def _join(values: Iterable[Any]) -> str:
    return normalize_text(" ".join(str(v or "") for v in values if str(v or "").strip()))


def _attachment_items(email: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    raw = email.get("attachments")
    parsed = _parse_jsonish(raw, raw if isinstance(raw, list) else [])
    if isinstance(parsed, list):
        attachments.extend(item for item in parsed if isinstance(item, dict))

    metadata = _parse_jsonish(email.get("metadata"), {})
    for item in metadata.get("attachments", []) if isinstance(metadata, dict) else []:
        if isinstance(item, dict):
            attachments.append(item)
    return attachments[:50]


def _attachment_path(item: Dict[str, Any]) -> Path:
    for key in ("path", "file_path", "local_path", "stored_path", "storage_path"):
        value = str(item.get(key) or "").strip()
        if value:
            return Path(value)
    return Path()


def _safe_read_bytes(path: Path) -> bytes:
    try:
        resolved = path.resolve()
        if not resolved.is_file() or resolved.stat().st_size > MAX_ATTACHMENT_BYTES:
            return b""
        return resolved.read_bytes()[:MAX_ATTACHMENT_BYTES]
    except (OSError, RuntimeError):
        return b""


def _decode_bytes(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding, errors="ignore")
        except LookupError:
            continue
    return data.decode(errors="ignore")


def _zip_xml_text(path: Path, prefixes: Tuple[str, ...]) -> str:
    parts: List[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.file_size > MAX_ATTACHMENT_BYTES:
                    continue
                name = info.filename.replace("\\", "/")
                if not any(name.startswith(prefix) for prefix in prefixes):
                    continue
                if not name.endswith(".xml"):
                    continue
                try:
                    raw = archive.read(info)[:MAX_ATTACHMENT_BYTES]
                    root = ElementTree.fromstring(raw)
                    parts.extend(node.text or "" for node in root.iter() if node.text)
                except Exception:
                    continue
    except (OSError, zipfile.BadZipFile):
        return ""
    return normalize_text(" ".join(parts))


def _extract_pdf_text(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return normalize_text(" ".join(page.extract_text() or "" for page in reader.pages[:25]))
    except Exception:
        return normalize_text(re.sub(r"[^\x09\x0A\x0D\x20-\x7E]+", " ", _decode_bytes(_safe_read_bytes(path))))


def _extract_image_ocr(path: Path) -> str:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
        with Image.open(path) as image:
            return normalize_text(pytesseract.image_to_string(image))
    except Exception:
        return ""


def _extract_attachment_text(item: Dict[str, Any]) -> Tuple[str, str]:
    path = _attachment_path(item)
    if not path:
        return "", ""
    filename = str(item.get("filename") or item.get("name") or path.name or "")
    content_type = str(item.get("content_type") or item.get("mime_type") or item.get("type") or "").lower()
    suffix = (path.suffix or Path(filename).suffix).lower()

    try:
        if suffix in TEXT_EXTENSIONS or content_type.startswith("text/"):
            text = _decode_bytes(_safe_read_bytes(path))
            return (strip_html(text) if suffix in {".html", ".htm"} or "html" in content_type else normalize_text(text)), ""
        if suffix == ".pdf" or "pdf" in content_type:
            return _extract_pdf_text(path), ""
        if suffix == ".docx":
            return _zip_xml_text(path, ("word/",)), ""
        if suffix == ".xlsx":
            return _zip_xml_text(path, ("xl/sharedStrings", "xl/worksheets/")), ""
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"} or content_type.startswith("image/"):
            return "", _extract_image_ocr(path)
    except Exception:
        return "", ""
    return "", ""


def build_search_document(email: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _parse_jsonish(email.get("metadata"), {})
    headers = email.get("headers") or (metadata.get("headers") if isinstance(metadata, dict) else None)
    recipients = _parse_jsonish(email.get("recipients"), email.get("recipients"))
    if isinstance(recipients, list):
        recipients_text = _join(recipients)
    else:
        recipients_text = normalize_text(recipients)

    attachments = _attachment_items(email)
    attachment_filenames = _join(
        item.get("filename") or item.get("name") or item.get("path") for item in attachments
    )
    attachment_types = _join(
        item.get("content_type") or item.get("mime_type") or item.get("type") or item.get("extension")
        for item in attachments
    )
    extracted_pairs = [_extract_attachment_text(item) for item in attachments]
    attachment_text = _join(
        [
            email.get("attachment_text"),
            *[
                item.get("text")
                or item.get("content")
                or item.get("text_content")
                or item.get("extracted_text")
                or item.get("preview")
                for item in attachments
            ],
            *[text for text, _ in extracted_pairs],
        ]
    )
    attachment_ocr_text = _join(
        [
            email.get("attachment_ocr_text"),
            *[item.get("ocr_text") or item.get("image_text") for item in attachments],
            *[ocr_text for _, ocr_text in extracted_pairs],
        ]
    )

    body = _join([
        email.get("body"),
        email.get("body_text"),
        strip_html(email.get("body_html")),
        email.get("snippet"),
    ])
    people = _join([
        email.get("sender"),
        email.get("sender_email"),
        email.get("from"),
        recipients_text,
        email.get("cc"),
        email.get("bcc"),
        email.get("reply_to"),
    ])
    headers_text = normalize_text(headers if isinstance(headers, str) else json.dumps(headers or {}, sort_keys=True))

    sources = {
        "subject": normalize_text(email.get("subject")),
        "sender": people,
        "body": body,
        "headers": headers_text,
        "snippet": normalize_text(email.get("snippet")),
        "attachment_filename": attachment_filenames,
        "attachment_type": attachment_types,
        "attachment_content": attachment_text,
        "ocr_text": attachment_ocr_text,
    }
    full_text = _join(sources.values())
    return {
        "sources": sources,
        "full_text": full_text,
        "attachment_text": attachment_text,
        "attachment_ocr_text": attachment_ocr_text,
        "attachments": attachments,
    }


def enrich_email_for_rules(email: Dict[str, Any], db: Any = None, persist: bool = True) -> Dict[str, Any]:
    enriched = dict(email or {})
    document = build_search_document(enriched)
    enriched["message_search_text"] = document["full_text"]
    enriched["attachment_text"] = document["attachment_text"]
    enriched["attachment_ocr_text"] = document["attachment_ocr_text"]
    enriched["attachments"] = document["attachments"]
    enriched["has_attachments"] = bool(document["attachments"])
    enriched["_rule_sources"] = document["sources"]
    if persist and db is not None and enriched.get("id") and hasattr(db, "update_email_scan_index"):
        try:
            db.update_email_scan_index(
                enriched["id"],
                search_text=document["full_text"],
                attachment_text=document["attachment_text"],
                attachment_ocr_text=document["attachment_ocr_text"],
                status="indexed",
            )
        except Exception:
            pass
    return enriched


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _field_to_source(field: str, condition_type: str = "") -> str:
    key = str(field or condition_type or "").lower().strip()
    mapping = {
        "subject": "subject",
        "subject_contains": "subject",
        "sender": "sender",
        "from": "sender",
        "sender_email": "sender",
        "sender_contains": "sender",
        "body": "body",
        "body_text": "body",
        "body_contains": "body",
        "snippet": "snippet",
        "headers": "headers",
        "attachment_name": "attachment_filename",
        "attachment_filename": "attachment_filename",
        "attachment_name_contains": "attachment_filename",
        "attachment_content": "attachment_content",
        "attachment_text": "attachment_content",
        "attachment_content_contains": "attachment_content",
        "ocr": "ocr_text",
        "ocr_text": "ocr_text",
        "entire_email": "full_text",
        "full_email": "full_text",
        "entire_email_contains": "full_text",
        "custom_keywords": "full_text",
    }
    return mapping.get(key, "full_text")


def _preview(source_text: str, needle: str = "") -> str:
    text = normalize_text(source_text)
    if not text:
        return ""
    lower = text.lower()
    marker = str(needle or "").lower()
    if marker and marker in lower:
        idx = max(lower.index(marker) - 48, 0)
        return text[idx:idx + MAX_PREVIEW_CHARS]
    return text[:MAX_PREVIEW_CHARS]


def _operator_match(source_text: str, operator: str, values: List[str], case_sensitive: bool = False,
                    use_regex: bool = False) -> Tuple[bool, str, str]:
    operator = str(operator or "contains").lower().strip()
    source = source_text if case_sensitive else source_text.lower()
    candidates = values or [""]
    needles = candidates if case_sensitive else [value.lower() for value in candidates]

    if use_regex or operator in {"regex", "regex_match"}:
        for raw in values:
            pattern = str(raw or "")[:200]
            try:
                if re.search(pattern, source_text[:MAX_SOURCE_CHARS], 0 if case_sensitive else re.IGNORECASE):
                    return True, raw, _preview(source_text, raw)
            except re.error:
                continue
        return False, "", ""

    if operator in {"has_attachment", "attachment_exists"}:
        return (bool(source_text), "has attachment", _preview(source_text))
    if operator in {"does_not_contain", "not_contains"}:
        ok = all(needle not in source for needle in needles if needle)
        return ok, ", ".join(values), _preview(source_text)
    if operator in {"equals", "is", "="}:
        for raw, needle in zip(values, needles):
            if source.strip() == needle.strip():
                return True, raw, _preview(source_text, raw)
        return False, "", ""
    if operator == "starts_with":
        for raw, needle in zip(values, needles):
            if source.startswith(needle):
                return True, raw, _preview(source_text, raw)
        return False, "", ""
    if operator == "ends_with":
        for raw, needle in zip(values, needles):
            if source.endswith(needle):
                return True, raw, _preview(source_text, raw)
        return False, "", ""
    if operator in {"all_keywords", "all"}:
        ok = all(needle in source for needle in needles if needle)
        return ok, ", ".join(values), _preview(source_text, values[0] if values else "")
    for raw, needle in zip(values, needles):
        if needle and needle in source:
            return True, raw, _preview(source_text, raw)
    return False, "", ""


def match_condition_payload(condition: Dict[str, Any], email: Dict[str, Any], match_mode: str = "any") -> Dict[str, Any]:
    condition = condition or {}
    sources = email.get("_rule_sources") or build_search_document(email)["sources"]
    ctype = str(condition.get("type") or "").lower()

    if ctype in {"and", "or"}:
        raw_children = condition.get("value") or []
        if not isinstance(raw_children, list):
            raw_children = [raw_children]
        children = [match_condition_payload(child, email, "all" if ctype == "and" else "any") for child in raw_children if isinstance(child, dict)]
        matched = all(child.get("matched") for child in children) if ctype == "and" else any(child.get("matched") for child in children)
        winner = next((child for child in children if child.get("matched")), {})
        return {"matched": matched, **{k: v for k, v in winner.items() if k != "matched"}}

    field = condition.get("field") or condition.get("scope")
    source_name = _field_to_source(field, ctype)
    source_text = (email.get("message_search_text") if source_name == "full_text" else sources.get(source_name)) or ""
    values = _as_list(condition.get("value") or condition.get("keywords") or condition.get("text"))
    operator = condition.get("operator") or ("has_attachment" if ctype in {"has_attachment", "has_attachments"} else "contains")
    matched, keyword, preview = _operator_match(
        source_text,
        operator,
        values,
        case_sensitive=bool(condition.get("case_sensitive")),
        use_regex=bool(condition.get("use_regex")),
    )
    return {
        "matched": matched,
        "matched_condition": ctype or str(field or "condition"),
        "matched_source": source_name if source_name != "full_text" else "entire_email",
        "matched_keyword": keyword,
        "matched_text_preview": preview,
    }
