"""
Shared types and constants for AI Email Organizer
"""

import os
from enum import Enum


class EmailCategory(str, Enum):
    FINANCE = "Finance"
    OTP = "OTP"
    CLIENTS = "Clients"
    PERSONAL = "Personal"
    PROMOTIONS = "Promotions"
    SPAM = "Spam"
    NEWSLETTERS = "Newsletters"
    TRADING = "Trading"
    LOGISTICS = "Logistics"
    PURCHASES = "Purchases"
    HR = "HR"
    SUPPORT = "Support"
    BILLS = "Bills"
    SECURITY = "Security"


class PriorityLevel(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class EmailProvider(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    IMAP = "imap"


class ActionType(str, Enum):
    AUTO_MOVE = "auto_move"
    SUGGEST = "suggest"
    NONE = "none"


CATEGORY_COLORS = {
    EmailCategory.FINANCE: "#4CAF50",
    EmailCategory.OTP: "#FF9800",
    EmailCategory.CLIENTS: "#2196F3",
    EmailCategory.PERSONAL: "#9C27B0",
    EmailCategory.PROMOTIONS: "#E91E63",
    EmailCategory.SPAM: "#F44336",
    EmailCategory.NEWSLETTERS: "#607D8B",
    EmailCategory.TRADING: "#00BCD4",
    EmailCategory.LOGISTICS: "#795548",
    EmailCategory.PURCHASES: "#3F51B5",
    EmailCategory.HR: "#FF5722",
    EmailCategory.SUPPORT: "#8BC34A",
    EmailCategory.BILLS: "#673AB7",
    EmailCategory.SECURITY: "#F44336",
}

SMART_VIEWS = [
    "Urgent",
    "Waiting Reply",
    "Finance",
    "Security",
    "Clients",
    "Orders",
    "Trading",
    "Promotions",
]

DEFAULT_CATEGORIES = [c.value for c in EmailCategory]

CONFIDENCE_THRESHOLDS = {
    "high": 0.95,
    "medium": 0.70,
    "low": 0.70,
}

_api_port = int(os.environ.get("API_PORT", "4597"))
API_CONFIG = {
    "host": "127.0.0.1",
    "port": _api_port,
    "base_url": f"http://127.0.0.1:{_api_port}",
}

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

OUTLOOK_SCOPES = [
    "Mail.Read",
    "Mail.ReadWrite",
    "MailboxSettings.ReadWrite",
]