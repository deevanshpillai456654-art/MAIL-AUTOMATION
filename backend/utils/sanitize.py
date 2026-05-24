"""
Data sanitization and validation utilities
"""

import html
import re
from typing import Dict, Optional


def sanitize_string(value: str, max_length: int = 10000) -> str:
    if not isinstance(value, str):
        return str(value)

    value = html.escape(value)

    value = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', value)

    return value[:max_length]


def sanitize_email(email: str) -> Optional[str]:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(pattern, email):
        return email.lower()
    return None


def sanitize_subject(subject: str) -> str:
    subject = re.sub(r'^Re:\s*', '', subject, flags=re.IGNORECASE)
    subject = re.sub(r'^Fw:\s*', '', subject, flags=re.IGNORECASE)
    subject = re.sub(r'\s+', ' ', subject)
    return sanitize_string(subject, max_length=500)


def sanitize_category(category: str) -> str:
    valid_categories = [
        "Finance", "OTP", "Clients", "Personal", "Promotions",
        "Spam", "Newsletters", "Trading", "Logistics", "Purchases",
        "HR", "Support", "Bills", "Security", "Urgent"
    ]

    if category in valid_categories:
        return category

    for valid in valid_categories:
        if valid.lower() == category.lower():
            return valid

    return "Personal"


def sanitize_priority(priority: str) -> str:
    valid_priorities = ["Low", "Medium", "High", "Critical"]

    if priority in valid_priorities:
        return priority

    for valid in valid_priorities:
        if valid.lower() == priority.lower():
            return valid

    return "Medium"


def sanitize_dict(data: Dict, fields: Dict[str, callable]) -> Dict:
    sanitized = {}

    for key, value in data.items():
        if key in fields:
            sanitizer = fields[key]
            try:
                sanitized[key] = sanitizer(value)
            except Exception:
                sanitized[key] = None
        else:
            sanitized[key] = value

    return sanitized


EMAIL_INPUT_FIELDS = {
    "subject": sanitize_string,
    "sender": sanitize_string,
    "sender_email": sanitize_email,
    "body": lambda x: sanitize_string(x, max_length=50000) if x else "",
    "category": sanitize_category,
    "priority": sanitize_priority
}


def sanitize_email_input(data: Dict) -> Dict:
    return sanitize_dict(data, EMAIL_INPUT_FIELDS)


def validate_confidence(confidence: float) -> float:
    return max(0.0, min(1.0, float(confidence)))


def remove_pii(text: str) -> str:
    patterns = [
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),
        (r'\b\d{2}/\d{2}/\d{4}\b', '[DATE]'),
        (r'\b[A-Z]{2}\d{6,}\b', '[ID]'),
        (r'\b\$\d+\.\d{2}\b', '[AMOUNT]'),
    ]

    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)

    return text


def redact_sensitive_data(data: Dict) -> Dict:
    sensitive_keys = ["password", "token", "secret", "key", "access_token", "refresh_token"]
    redacted = data.copy()

    for key in sensitive_keys:
        if key in redacted:
            redacted[key] = "***REDACTED***"

    return redacted
