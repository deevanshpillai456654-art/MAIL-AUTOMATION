from __future__ import annotations

from typing import Any, Dict

COMMON_PROVIDERS = {
    "gmail.com": {"provider":"gmail", "imap_host":"imap.gmail.com", "imap_port":993, "smtp_host":"smtp.gmail.com", "smtp_port":465, "ssl":True},
    "googlemail.com": {"provider":"gmail", "imap_host":"imap.gmail.com", "imap_port":993, "smtp_host":"smtp.gmail.com", "smtp_port":465, "ssl":True},
    "outlook.com": {"provider":"outlook", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "hotmail.com": {"provider":"outlook", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "live.com": {"provider":"outlook", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "msn.com": {"provider":"outlook", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "office365.com": {"provider":"microsoft365", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "onmicrosoft.com": {"provider":"microsoft365", "imap_host":"outlook.office365.com", "imap_port":993, "smtp_host":"smtp.office365.com", "smtp_port":587, "ssl":True},
    "yahoo.com": {"provider":"yahoo", "imap_host":"imap.mail.yahoo.com", "imap_port":993, "smtp_host":"smtp.mail.yahoo.com", "smtp_port":465, "ssl":True},
    "ymail.com": {"provider":"yahoo", "imap_host":"imap.mail.yahoo.com", "imap_port":993, "smtp_host":"smtp.mail.yahoo.com", "smtp_port":465, "ssl":True},
    "rocketmail.com": {"provider":"yahoo", "imap_host":"imap.mail.yahoo.com", "imap_port":993, "smtp_host":"smtp.mail.yahoo.com", "smtp_port":465, "ssl":True},
    "zoho.com": {"provider":"zoho", "imap_host":"imap.zoho.com", "imap_port":993, "smtp_host":"smtp.zoho.com", "smtp_port":465, "ssl":True},
    "zohomail.com": {"provider":"zoho", "imap_host":"imap.zoho.com", "imap_port":993, "smtp_host":"smtp.zoho.com", "smtp_port":465, "ssl":True},
    "icloud.com": {"provider":"icloud", "imap_host":"imap.mail.me.com", "imap_port":993, "smtp_host":"smtp.mail.me.com", "smtp_port":587, "ssl":True},
    "me.com": {"provider":"icloud", "imap_host":"imap.mail.me.com", "imap_port":993, "smtp_host":"smtp.mail.me.com", "smtp_port":587, "ssl":True},
    "mac.com": {"provider":"icloud", "imap_host":"imap.mail.me.com", "imap_port":993, "smtp_host":"smtp.mail.me.com", "smtp_port":587, "ssl":True},
    "proton.me": {"provider":"proton", "imap_host":"127.0.0.1", "imap_port":1143, "smtp_host":"127.0.0.1", "smtp_port":1025, "ssl":True},
    "protonmail.com": {"provider":"proton", "imap_host":"127.0.0.1", "imap_port":1143, "smtp_host":"127.0.0.1", "smtp_port":1025, "ssl":True},
    "pm.me": {"provider":"proton", "imap_host":"127.0.0.1", "imap_port":1143, "smtp_host":"127.0.0.1", "smtp_port":1025, "ssl":True},
    "fastmail.com": {"provider":"fastmail", "imap_host":"imap.fastmail.com", "imap_port":993, "smtp_host":"smtp.fastmail.com", "smtp_port":465, "ssl":True},
    "aol.com": {"provider":"aol", "imap_host":"imap.aol.com", "imap_port":993, "smtp_host":"smtp.aol.com", "smtp_port":465, "ssl":True},
}

def detect_mail_settings(email: str) -> Dict[str, Any]:
    domain = (email or "").split("@")[-1].lower().strip()
    detected = COMMON_PROVIDERS.get(domain)
    if not detected and domain.endswith(".onmicrosoft.com"):
        detected = COMMON_PROVIDERS["onmicrosoft.com"]
    if detected:
        return {"email": email, "domain": domain, "detected": True, **detected}
    return {"email": email, "domain": domain, "detected": False, "provider":"custom", "imap_host": f"imap.{domain}" if domain else "", "imap_port":993, "smtp_host": f"smtp.{domain}" if domain else "", "smtp_port":465, "ssl": True}

def account_metadata(sync_interval: int = 20, **kwargs) -> Dict[str, Any]:
    interval = int(sync_interval or 20)
    if interval not in (20,30,60): interval = 20
    data = {"sync_interval": interval, "preserve_on_update": True, "manual_removal_only": True}
    data.update({k:v for k,v in kwargs.items() if v not in (None, "")})
    return data
