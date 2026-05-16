"""
API Client for AI Email Organizer
Use this in external applications to communicate with the local service
"""

import requests
from typing import Optional, Dict, List, Any


class EmailOrganizerClient:
    def __init__(self, base_url: str = "http://127.0.0.1:4597"):
        self.base_url = base_url
        self.api_version = "api/v1"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/{self.api_version}"

    def check_health(self) -> bool:
        try:
            response = requests.get(f"{self.api_url}/health", timeout=5)
            return response.ok
        except requests.RequestException:
            return False

    def classify_email(
        self,
        subject: str,
        sender: str,
        sender_email: str,
        body: Optional[str] = None
    ) -> Optional[Dict]:
        try:
            response = requests.post(
                f"{self.api_url}/classify",
                json={
                    "subject": subject,
                    "sender": sender,
                    "sender_email": sender_email,
                    "body": body or ""
                },
                timeout=10
            )
            if response.ok:
                return response.json()
        except requests.RequestException:
            return None
        return None

    def submit_feedback(
        self,
        email_id: int,
        predicted_category: str,
        actual_category: str,
        user_id: int = 1
    ) -> bool:
        try:
            response = requests.post(
                f"{self.api_url}/feedback",
                json={
                    "email_id": email_id,
                    "predicted_category": predicted_category,
                    "actual_category": actual_category,
                    "user_id": user_id
                },
                timeout=5
            )
            return response.ok
        except requests.RequestException:
            return False

    def get_categories(self) -> List[str]:
        try:
            response = requests.get(f"{self.api_url}/categories", timeout=5)
            if response.ok:
                return response.json().get("categories", [])
        except requests.RequestException:
            pass
        return []

    def get_smart_views(self) -> List[str]:
        try:
            response = requests.get(f"{self.api_url}/smart-views", timeout=5)
            if response.ok:
                return response.json().get("views", [])
        except requests.RequestException:
            pass
        return []

    def search_emails(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        try:
            response = requests.post(
                f"{self.api_url}/search",
                json={
                    "query": query,
                    "category": category,
                    "limit": limit
                },
                timeout=10
            )
            if response.ok:
                return response.json().get("emails", [])
        except requests.RequestException:
            pass
        return []

    def process_email(self, email_data: Dict) -> Optional[Dict]:
        try:
            response = requests.post(
                f"{self.api_url}/email/process",
                json=email_data,
                timeout=10
            )
            if response.ok:
                return response.json()
        except requests.RequestException:
            pass
        return None


def main():
    client = EmailOrganizerClient()

    print("AI Email Organizer Client")
    print("=" * 30)

    if client.check_health():
        print("Service: Online")

        result = client.classify_email(
            subject="Your verification code",
            sender="Google",
            sender_email="noreply@google.com",
            body="Your code is 123456"
        )
        if result:
            print(f"Classification: {result.get('category')}")
            print(f"Confidence: {result.get('confidence')}")
            print(f"Priority: {result.get('priority')}")

        categories = client.get_categories()
        print(f"Categories: {', '.join(categories[:5])}...")
    else:
        print("Service: Offline")


if __name__ == "__main__":
    main()