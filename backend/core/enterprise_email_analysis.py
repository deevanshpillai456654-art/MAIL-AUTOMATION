from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from backend.core.scam_filter import ScamFilter

INTENTS = {
    "rfq": ["rfq", "request for quote", "quotation", "quote", "pricing", "rate request"],
    "invoice": ["invoice", "bill", "payment due", "gst", "tax invoice"],
    "shipment": ["shipment", "tracking", "awb", "bl", "container", "dispatch", "delivery"],
    "support": ["support", "issue", "problem", "help", "not working", "ticket"],
    "complaint": ["complaint", "delay", "damaged", "escalation", "bad service"],
    "lead": ["interested", "requirement", "need service", "contact me", "proposal"],
    "customs": ["customs", "icegate", "boe", "shipping bill", "cha"],
    "marketing": ["campaign", "marketing", "brand", "webinar", "product launch", "content calendar"],
    "sales": ["demo request", "pricing request", "quote request", "sales proposal", "book a demo"],
    "social_media": ["linkedin", "instagram", "facebook", "twitter", "youtube", "new follower", "mention"],
    "investor": ["investor", "funding", "term sheet", "pitch deck", "due diligence", "cap table"],
    "scam": ["verify your account", "account suspended", "gift card", "seed phrase", "claim your prize"],
}
ENTITY_PATTERNS = {
    "invoice_numbers": r"\b(?:INV|INVOICE|BILL)[-\s:#]*([A-Z0-9-]{4,})\b",
    "tracking_ids": r"\b(?:AWB|TRACKING|LR|BL|B/L)[-\s:#]*([A-Z0-9-]{5,})\b",
    "phone_numbers": r"(?:(?:\+91[-\s]?)|0)?[6-9]\d{9}\b",
    "emails": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "dates": r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2})\b",
    "container_numbers": r"\b[A-Z]{4}\d{7}\b",
}

def _contains(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)

def analyze_email_content(payload: Dict[str, Any]) -> Dict[str, Any]:
    subject = str(payload.get("subject") or "")
    body = str(payload.get("body") or payload.get("body_text") or payload.get("plain_text") or "")
    html = str(payload.get("html") or payload.get("body_html") or "")
    sender = str(payload.get("sender_email") or payload.get("sender") or "")
    headers = payload.get("headers") or {}
    attachments = payload.get("attachments") or []
    full = " ".join([subject, body, re.sub(r"<[^>]+>", " ", html), sender, json.dumps(headers, default=str)]).lower()
    scam = ScamFilter().classify(subject=subject, sender=sender, sender_email=sender, body=body or html)
    if scam:
        entities = {name: sorted(set(re.findall(pattern, subject + "\n" + body + "\n" + html, flags=re.I))) for name, pattern in ENTITY_PATTERNS.items()}
        return {
            "status": "analyzed",
            "classification": "Scam",
            "intents": ["scam"],
            "priority": scam.get("priority", "Critical"),
            "confidence": scam.get("confidence", 0.9),
            "entities": entities,
            "attachment_types": [],
            "sender_domain": sender.split("@")[-1].lower() if "@" in sender else "",
            "recommended_actions": recommended_actions("Scam", "Critical"),
            "lifecycle_stage": "Quarantine",
            "scam_reasons": scam.get("scam_reasons", []),
        }
    matched = [name for name, words in INTENTS.items() if _contains(full, words)]
    if not matched:
        matched = ["general"]
    urgency_terms = ["urgent", "asap", "immediately", "critical", "today", "priority"]
    urgency = "High" if _contains(full, urgency_terms) else "Medium"
    entities = {name: sorted(set(re.findall(pattern, subject + "\n" + body + "\n" + html, flags=re.I))) for name, pattern in ENTITY_PATTERNS.items()}
    attachment_types = []
    for item in attachments if isinstance(attachments, list) else []:
        name = str(item.get("filename") if isinstance(item, dict) else item).lower()
        if "." in name:
            attachment_types.append(name.rsplit(".", 1)[-1])
    primary = matched[0]
    category = {
        "rfq": "RFQ", "invoice": "Invoice", "shipment": "Shipment", "support": "Support", "complaint": "Complaint", "lead": "Leads", "customs": "Customs",
        "marketing": "Marketing", "sales": "Sales", "social_media": "Social Media", "investor": "Investor", "scam": "Scam",
    }.get(primary, "General")
    confidence = 0.93 if primary != "general" else 0.64
    return {
        "status": "analyzed",
        "classification": category,
        "intents": matched,
        "priority": urgency,
        "confidence": confidence,
        "entities": entities,
        "attachment_types": sorted(set(attachment_types)),
        "sender_domain": sender.split("@")[-1].lower() if "@" in sender else "",
        "recommended_actions": recommended_actions(category, urgency),
        "lifecycle_stage": "Analyzed",
    }

def recommended_actions(category: str, urgency: str) -> List[str]:
    actions = []
    if category == "Scam": actions += ["move_to_folder:Scam", "apply_label:Scam", "mark_priority_critical"]
    if category == "RFQ": actions += ["create_crm_lead", "forward_to_sales", "apply_label:RFQ"]
    if category == "Invoice": actions += ["apply_label:Finance", "extract_invoice_number"]
    if category == "Support": actions += ["assign_support", "notify_team"]
    if category == "Leads": actions += ["create_crm_lead", "apply_label:Leads"]
    if category == "Sales": actions += ["apply_label:Sales", "mark_priority_high"]
    if category == "Marketing": actions += ["apply_label:Marketing"]
    if category == "Investor": actions += ["apply_label:Investor", "mark_priority_high"]
    if category == "Social Media": actions += ["apply_label:Social Media"]
    if urgency == "High": actions.append("mark_priority_high")
    return actions or ["apply_label:Reviewed"]
