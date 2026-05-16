import os
import tempfile
import unittest

from backend.db.database import Database
from backend.auth.gmail_auth import GmailOAuth


class TestAccountOAuthSync(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_file.close()
        self.db = Database(self.temp_file.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.temp_file.name)

    def test_oauth_configuration_rejects_default_credentials(self):
        oauth = GmailOAuth(db=self.db, client_id="YOUR_GMAIL_CLIENT_ID", client_secret="YOUR_GMAIL_CLIENT_SECRET")

        result = oauth.validate_configuration()

        self.assertFalse(result["configured"])
        self.assertIn("GMAIL_CLIENT_ID", result["missing"])
        self.assertIn("GMAIL_CLIENT_SECRET", result["missing"])

    def test_oauth_state_can_only_be_consumed_once(self):
        self.db.create_oauth_state(
            provider="gmail",
            state="state-123",
            code_verifier="verifier-123",
            redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
            expires_at="2999-01-01T00:00:00",
        )

        first = self.db.consume_oauth_state("gmail", "state-123")
        second = self.db.consume_oauth_state("gmail", "state-123")

        self.assertIsNotNone(first)
        self.assertEqual(first["code_verifier"], "verifier-123")
        self.assertIsNone(second)

    def test_upsert_account_preserves_single_account_per_provider_email(self):
        first = self.db.upsert_account(
            provider="imap",
            email="user@example.com",
            status="connected",
            metadata={"host": "imap.example.com"},
        )
        second = self.db.upsert_account(
            provider="imap",
            email="user@example.com",
            status="needs_reconnect",
            metadata={"host": "imap2.example.com"},
        )

        accounts = self.db.fetch_all("SELECT * FROM accounts WHERE email = ?", ("user@example.com",))

        self.assertEqual(first, second)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["status"], "needs_reconnect")
        self.assertIn("imap2.example.com", accounts[0]["metadata"])

    def test_sync_progress_does_not_set_completion_time_until_terminal_status(self):
        account_id = self.db.upsert_account(provider="imap", email="user@example.com", status="connected")
        sync_id = self.db.add_sync_status(account_id, "pending")

        self.db.update_sync_status(sync_id, "in_progress", progress=40, processed_emails=4, total_emails=10)
        in_progress = self.db.fetch_one("SELECT * FROM sync_status WHERE id = ?", (sync_id,))
        self.assertIsNone(in_progress["completed_at"])

        self.db.update_sync_status(sync_id, "completed", progress=100, processed_emails=10, total_emails=10)
        completed = self.db.fetch_one("SELECT * FROM sync_status WHERE id = ?", (sync_id,))
        self.assertIsNotNone(completed["completed_at"])


if __name__ == "__main__":
    unittest.main()
