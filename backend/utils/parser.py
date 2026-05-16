"""
Email parsing utilities for AI Email Organizer
"""

import re
import json
from typing import Dict, Optional, List
from email.utils import parseaddr
from datetime import datetime
from html import unescape


class EmailParser:
    """Parse and extract information from emails"""

    def __init__(self):
        self.extraction_patterns = {
            "invoice": [
                r"Invoice\s*#?\s*(\d+)",
                r"Invoice\s+Date:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"Amount:\s*\$?([\d,]+\.?\d*)",
                r"Total\s*Amount:\s*\$?([\d,]+\.?\d*)",
            ],
            "order": [
                r"Order\s*#?\s*([A-Z0-9-]+)",
                r"Order\s+Date:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"Tracking\s+Number:\s*([A-Z0-9]+)",
            ],
            "otp": [
                r"(\d{4,8})\s*(?:is\s*)?(?:your\s*)?(?:verification\s*)?(?:code)?",
                r"code[:\s]+(\d{4,8})",
            ],
            "date": [
                r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                r"(\w+\s+\d{1,2},?\s+\d{4})",
            ],
            "amount": [
                r"\$([\d,]+\.?\d*)",
                r"([\d,]+\.?\d*)\s*(?:USD|EUR|GBP)",
            ],
        }

    def parse_headers(self, headers: Dict) -> Dict:
        """Extract and normalize email headers"""
        header_map = {k.lower(): v for k, v in headers.items()}

        sender = parseaddr(header_map.get("from", ""))
        to = parseaddr(header_map.get("to", ""))
        cc = parseaddr(header_map.get("cc", ""))

        return {
            "subject": header_map.get("subject", ""),
            "from_name": sender[0],
            "from_email": sender[1],
            "to_name": to[0],
            "to_email": to[1],
            "cc_email": cc[1],
            "date": header_map.get("date", ""),
            "message_id": header_map.get("message-id", ""),
            "reply_to": header_map.get("reply-to", ""),
        }

    def extract_body(self, payload: Dict) -> str:
        """Extract text body from email payload"""
        if "body" in payload and payload["body"]:
            return self._clean_text(payload["body"])

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                body = part.get("body", {}).get("data", "")
                if body:
                    return self._decode_body(body)

            if part.get("mimeType") == "text/html":
                body = part.get("body", {}).get("data", "")
                if body:
                    html = self._decode_body(body)
                    return self._strip_html(html)

        return ""

    def _decode_body(self, encoded: str) -> str:
        """Decode base64 or URL-safe encoded body"""
        try:
            import base64
            decoded = base64.urlsafe_b64decode(encoded + "==")
            return decoded.decode("utf-8", errors="ignore")
        except Exception:
            return encoded

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        text = unescape(text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        return text.strip()

    def _strip_html(self, html: str) -> str:
        """Strip HTML tags from content"""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = unescape(text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def extract_attachments(self, payload: Dict) -> List[Dict]:
        """Extract attachment information"""
        attachments = []
        parts = payload.get("parts", [])

        for part in parts:
            if part.get("filename"):
                attachments.append({
                    "filename": part.get("filename", ""),
                    "mime_type": part.get("mimeType", "application/octet-stream"),
                    "size": part.get("body", {}).get("size", 0),
                })

        return attachments

    def extract_entities(self, text: str) -> Dict:
        """Extract structured entities from email"""
        entities = {
            "invoice_numbers": [],
            "order_numbers": [],
            "otp_codes": [],
            "dates": [],
            "amounts": [],
            "urls": [],
            "phone_numbers": [],
        }

        for pattern in self.extraction_patterns.get("invoice", []):
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities["invoice_numbers"].extend(matches)

        for pattern in self.extraction_patterns.get("order", []):
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities["order_numbers"].extend(matches)

        for pattern in self.extraction_patterns.get("otp", []):
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities["otp_codes"].extend(matches)

        for pattern in self.extraction_patterns.get("amount", []):
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities["amounts"].extend(matches)

        url_pattern = r'https?://[^\s]+'
        entities["urls"] = re.findall(url_pattern, text)

        phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
        entities["phone_numbers"] = re.findall(phone_pattern, text)

        return entities

    def parse_email(self, raw_email: Dict) -> Dict:
        """Full email parsing pipeline"""
        headers = self.parse_headers(raw_email.get("headers", {}))
        body = self.extract_body(raw_email.get("payload", {}))
        attachments = self.extract_attachments(raw_email.get("payload", {}))
        entities = self.extract_entities(body)

        return {
            "headers": headers,
            "body": body,
            "attachments": attachments,
            "entities": entities,
            "parsed_at": datetime.now().isoformat(),
        }


class EmailNormalizer:
    """Normalize and clean email content for classification"""

    @staticmethod
    def normalize_subject(subject: str) -> str:
        subject = re.sub(r'^Re:\s*', '', subject, flags=re.IGNORECASE)
        subject = re.sub(r'^Fw:\s*', '', subject, flags=re.IGNORECASE)
        subject = re.sub(r'\[.*?\]', '', subject)
        return subject.strip()

    @staticmethod
    def normalize_sender(sender: str) -> str:
        name, email = parseaddr(sender)
        if email:
            return email.lower()
        return sender.lower()

    @staticmethod
    def truncate_body(body: str, max_length: int = 5000) -> str:
        return body[:max_length] if len(body) > max_length else body

    @staticmethod
    def extract_domain(email: str) -> str:
        match = re.search(r'@([a-zA-Z0-9.-]+)', email)
        return match.group(1).lower() if match else ""


def parse_gmail_message(message: Dict) -> Dict:
    """Parse Gmail API message format"""
    parser = EmailParser()

    headers = {}
    for header in message.get("payload", {}).get("headers", []):
        headers[header["name"]] = header["value"]

    raw_email = {
        "headers": headers,
        "payload": message.get("payload", {}),
    }

    parsed = parser.parse_email(raw_email)

    return {
        "message_id": message.get("id", ""),
        "subject": parsed["headers"]["subject"],
        "from": parsed["headers"]["from_email"],
        "from_name": parsed["headers"]["from_name"],
        "body": parsed["body"],
        "attachments": parsed["attachments"],
        "entities": parsed["entities"],
        "labels": message.get("labelIds", []),
        "snippet": message.get("snippet", ""),
    }


def parse_outlook_message(message: Dict) -> Dict:
    """Parse Microsoft Graph message format"""
    parser = EmailParser()

    from_field = message.get("from", {})
    from_email = from_field.get("emailAddress", {})

    raw_email = {
        "headers": {
            "subject": message.get("subject", ""),
            "from": f"{from_email.get('name', '')} <{from_email.get('address', '')}>",
            "to": ", ".join([r.get("emailAddress", {}).get("address", "") for r in message.get("toRecipients", [])]),
            "date": message.get("receivedDateTime", ""),
        },
        "payload": {
            "body": {"data": message.get("body", {}).get("content", "")},
            "parts": [],
        },
    }

    parsed = parser.parse_email(raw_email)

    return {
        "message_id": message.get("id", ""),
        "subject": parsed["headers"]["subject"],
        "from": parsed["headers"]["from_email"],
        "from_name": parsed["headers"]["from_name"],
        "body": parsed["body"],
        "attachments": [],
        "entities": parsed["entities"],
        "categories": message.get("categories", []),
        "is_read": message.get("isRead", True),
    }