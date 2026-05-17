import sqlite3
import os
import threading
import time
from typing import Optional
from datetime import datetime, timezone
import json
import atexit
from contextlib import contextmanager
from backend.core.mailbox_infrastructure_guard import (
    bucket_name_from_provider_item,
    canonical_bucket_key,
    canonical_rule_values,
    display_bucket_name,
    forwarding_actions,
    forwarding_condition_signature,
    recipient_list,
    recipients_signature,
)


class Database:
    _instance = None
    _lock = threading.Lock()
    _instances = set()


    def __new__(cls, db_path: str = None):
        if db_path is None:
            from backend import config
            db_path = config.DB_PATH
        with cls._lock:
            if cls._instance is None or getattr(cls._instance, "db_path", None) != db_path:
                if cls._instance is not None:
                    try:
                        cls._instance.close_all_connections()
                    except Exception:
                        pass
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
                cls._instances.add(cls._instance)
        return cls._instance

    def __init__(self, db_path: str = None):
        if db_path is None:
            from backend import config
            db_path = config.DB_PATH
        if self._initialized and hasattr(self, 'db_path') and self.db_path == db_path:
            return
            
        self.db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._connections_lock = threading.Lock()
        self._connections = []
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        self._initialized = True
        self._busy_timeout = 30000  # 30 seconds
        self._pragmas_applied = False

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self._busy_timeout / 1000,
                check_same_thread=False,
                isolation_level=None  # Autocommit mode for better concurrency
            )
            conn.row_factory = sqlite3.Row
            
            self._apply_pragmas(conn)
            self._pragmas_applied = True
            
            self._local.conn = conn
            self._register_connection(conn)
        
        return self._local.conn

    def _register_connection(self, conn: sqlite3.Connection) -> None:
        with self._connections_lock:
            if all(existing is not conn for existing in self._connections):
                self._connections.append(conn)

    def _unregister_connection(self, conn: sqlite3.Connection) -> None:
        with self._connections_lock:
            self._connections = [existing for existing in self._connections if existing is not conn]

    def close(self):
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None
                self._unregister_connection(conn)
                self._pragmas_applied = False

    def close_all_connections(self):
        with self._connections_lock:
            conns = list(self._connections)
            self._connections = []
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass
        if hasattr(self._local, 'conn'):
            self._local.conn = None
        self._pragmas_applied = False

    @classmethod
    def close_all_instances(cls):
        with cls._lock:
            instances = list(cls._instances)
        for instance in instances:
            try:
                instance.close_all_connections()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close_all_connections()
        except Exception:
            pass

    def _apply_pragmas(self, conn: sqlite3.Connection):
        """Apply performance and safety pragmas"""
        pragmas = [
            ("journal_mode", "WAL"),
            ("synchronous", "NORMAL"),
            ("cache_size", "-2000"),  # 2MB cache
            ("temp_store", "MEMORY"),
            ("mmap_size", "268435456"),  # 256MB mmap
            ("busy_timeout", str(self._busy_timeout)),
            ("foreign_keys", "ON"),
            ("ignore_check_constraints", "OFF"),
        ]
        
        for key, value in pragmas:
            try:
                conn.execute(f"PRAGMA {key} = {value}")
            except sqlite3.Error:
                pass

    @contextmanager
    def get_cursor(self):
        """Context manager for database operations"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            self.close()

    def _init_db(self):
        """Initialize database schema - called once"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                provider TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                provider TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                token_expiry TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        self._ensure_column(cursor, "accounts", "status", "TEXT DEFAULT 'connected'")
        self._ensure_column(cursor, "accounts", "reconnect_state", "TEXT DEFAULT 'ok'")
        self._ensure_column(cursor, "accounts", "last_error", "TEXT")
        self._ensure_column(cursor, "accounts", "last_sync_at", "TIMESTAMP")
        self._ensure_column(cursor, "accounts", "sync_checkpoint", "TEXT")
        self._ensure_column(cursor, "accounts", "metadata", "TEXT")
        self._ensure_column(cursor, "accounts", "updated_at", "TIMESTAMP")
        self._ensure_column(cursor, "accounts", "auth_type", "TEXT")
        self._ensure_column(cursor, "accounts", "oauth_provider", "TEXT")
        self._ensure_column(cursor, "accounts", "token_scopes", "TEXT")
        self._ensure_column(cursor, "accounts", "sync_status", "TEXT DEFAULT 'idle'")
        self._ensure_column(cursor, "accounts", "webhook_enabled", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "accounts", "provider_capabilities", "TEXT")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                message_id TEXT,
                subject TEXT,
                sender TEXT,
                sender_email TEXT,
                body_text TEXT,
                body_html TEXT,
                category TEXT,
                confidence REAL,
                priority TEXT DEFAULT 'Medium',
                is_read INTEGER DEFAULT 0,
                is_processed INTEGER DEFAULT 0,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)

        # Rule-action state.  Existing databases are migrated in place so
        # installer/upgrades keep user mail and rule data intact.
        self._ensure_column(cursor, "emails", "folder", "TEXT DEFAULT 'INBOX'")
        self._ensure_column(cursor, "emails", "labels", "TEXT DEFAULT '[]'")
        self._ensure_column(cursor, "emails", "rule_status", "TEXT")
        self._ensure_column(cursor, "emails", "rule_applied_at", "TIMESTAMP")
        self._ensure_column(cursor, "emails", "provider_action_error", "TEXT")
        self._ensure_column(cursor, "emails", "forward_status", "TEXT")
        self._ensure_column(cursor, "emails", "forwarded_at", "TIMESTAMP")
        self._ensure_column(cursor, "emails", "forwarded_to", "TEXT")
        self._ensure_column(cursor, "emails", "forward_error", "TEXT")
        self._ensure_column(cursor, "emails", "delete_state", "TEXT DEFAULT 'active'")
        self._ensure_column(cursor, "emails", "deleted_at", "TIMESTAMP")
        self._ensure_column(cursor, "emails", "restore_snapshot", "TEXT")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, name)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                UNIQUE(account_id, name)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                account_id INTEGER,
                label TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email_id, label),
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rule_action_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                rule_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_value TEXT,
                local_success INTEGER DEFAULT 0,
                provider_success INTEGER DEFAULT 0,
                provider_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_forward_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                account_id INTEGER,
                provider TEXT,
                rule_name TEXT,
                recipients TEXT NOT NULL,
                cc TEXT DEFAULT '[]',
                bcc TEXT DEFAULT '[]',
                subject TEXT,
                local_success INTEGER DEFAULT 0,
                provider_success INTEGER DEFAULT 0,
                provider_status TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_forwarding_flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                provider TEXT,
                provider_rule_id TEXT,
                condition_signature TEXT NOT NULL,
                recipients_signature TEXT NOT NULL,
                recipients TEXT NOT NULL,
                status TEXT DEFAULT 'synced',
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, condition_signature, recipients_signature)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                condition TEXT NOT NULL,
                action TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL,
                model_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                predicted_category TEXT,
                actual_category TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS classification_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sender_email TEXT NOT NULL,
                sender_domain TEXT,
                category TEXT NOT NULL,
                source_email_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, sender_email)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                vector BLOB NOT NULL,
                model TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender_email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_created ON emails(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(folder)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_delete_state ON emails(delete_state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_labels_email ON email_labels(email_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_labels_label ON email_labels(label)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_labels_name ON mail_labels(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_folders_name ON mail_folders(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_forward_email ON email_forward_audit(email_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_forward_provider ON email_forward_audit(provider)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_forwarding_flows_account ON mail_forwarding_flows(account_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_forwarding_flows_signature ON mail_forwarding_flows(condition_signature, recipients_signature)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_email ON feedback(email_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_classification_overrides_sender ON classification_overrides(sender_email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_classification_overrides_user ON classification_overrides(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
        # Composite indexes for the most common query patterns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_account_id ON emails(account_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_account_created ON emails(account_id, created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_account_processed ON emails(account_id, is_processed)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_account_category ON emails(account_id, category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
        
        # Sync status table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                total_emails INTEGER DEFAULT 0,
                processed_emails INTEGER DEFAULT 0,
                last_error TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_account ON sync_status(account_id)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                state TEXT NOT NULL UNIQUE,
                code_verifier TEXT,
                redirect_uri TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                consumed_at TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_oauth_states_provider_state ON oauth_states(provider, state)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provider_diagnostics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_provider_diagnostics_account ON provider_diagnostics(account_id)")
        
        # AI Memory tables for adaptive learning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_type TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                confidence_threshold_high REAL DEFAULT 0.85,
                confidence_threshold_low REAL DEFAULT 0.3,
                notification_enabled INTEGER DEFAULT 1,
                vip_senders TEXT DEFAULT '[]',
                muted_senders TEXT DEFAULT '[]',
                preferred_categories TEXT DEFAULT '{}',
                notification_timing TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS behavioral_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                pattern_type TEXT NOT NULL,
                pattern_features TEXT,
                confidence REAL DEFAULT 0.5,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                occurrence_count INTEGER DEFAULT 1
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email_id INTEGER NOT NULL,
                sender_email TEXT NOT NULL,
                signal TEXT NOT NULL,
                action TEXT NOT NULL,
                category TEXT,
                priority TEXT,
                response_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_memory_user ON ai_memory(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_memory_type ON ai_memory(memory_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_feedback_user ON learning_feedback(user_id)")
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        conn.commit()
        conn.close()

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def execute(self, query: str, params: tuple = ()) -> int:
        """Thread-safe write operation"""
        with self._write_lock:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.lastrowid

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        """Thread-safe read operation"""
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            result = cursor.fetchone()
            return dict(result) if result else None

    def fetch_all(self, query: str, params: tuple = ()) -> list:
        """Thread-safe read operation"""
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            return [dict(row) for row in results]

    def execute_many(self, query: str, params_list: list) -> int:
        """Thread-safe batch write"""
        with self._write_lock:
            with self.get_cursor() as cursor:
                cursor.executemany(query, params_list)
                return cursor.rowcount

    def add_user(self, email: str, provider: str, settings: Optional[dict] = None) -> int:
        existing = self.get_user_by_email(email)
        if existing:
            return existing["id"]

        return self.execute(
            "INSERT INTO users (email, provider, settings) VALUES (?, ?, ?)",
            (email, provider, json.dumps(settings) if settings else None)
        )

    def add_account(self, user_id: int, email: str, provider: str, access_token: str = None, refresh_token: str = None) -> int:
        return self.upsert_account(
            provider=provider,
            email=email,
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def upsert_account(self, provider: str, email: str, user_id: int = None, access_token: str = None,
                       refresh_token: str = None, token_expiry: str = None, status: str = "connected",
                       reconnect_state: str = "ok", metadata: Optional[dict] = None,
                       last_error: str = None, sync_checkpoint: str = None,
                       auth_type: str = None, oauth_provider: str = None,
                       token_scopes: str = None, sync_status: str = None,
                       webhook_enabled: int = None, provider_capabilities: str = None) -> int:
        email = (email or "").strip().lower()
        provider = (provider or "").strip().lower()
        if not email:
            raise ValueError("Account email is required")
        if not provider:
            raise ValueError("Account provider is required")

        if user_id is None:
            user_id = self.add_user(email, provider)

        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        now = datetime.now().isoformat()
        existing = self.fetch_one(
            "SELECT id FROM accounts WHERE provider = ? AND email = ? ORDER BY id LIMIT 1",
            (provider, email)
        )

        if existing:
            query = """
                UPDATE accounts
                SET user_id = ?, status = ?, reconnect_state = ?, metadata = ?, updated_at = ?,
                    last_error = ?
            """
            params = [user_id, status, reconnect_state, metadata_json, now, last_error]

            optional_columns = {
                "auth_type": auth_type,
                "oauth_provider": oauth_provider,
                "token_scopes": token_scopes,
                "sync_status": sync_status,
                "webhook_enabled": webhook_enabled,
                "provider_capabilities": provider_capabilities,
            }
            for column, value in optional_columns.items():
                if value is not None:
                    query += f", {column} = ?"
                    params.append(value)

            if access_token is not None:
                query += ", access_token = ?"
                params.append(access_token)
            if refresh_token is not None:
                query += ", refresh_token = ?"
                params.append(refresh_token)
            if token_expiry is not None:
                query += ", token_expiry = ?"
                params.append(token_expiry)
            if sync_checkpoint is not None:
                query += ", sync_checkpoint = ?"
                params.append(sync_checkpoint)

            query += " WHERE id = ?"
            params.append(existing["id"])
            self.execute(query, tuple(params))
            return existing["id"]

        return self.execute(
            """INSERT INTO accounts
               (user_id, email, provider, access_token, refresh_token, token_expiry, status,
                reconnect_state, last_error, sync_checkpoint, metadata, updated_at,
                auth_type, oauth_provider, token_scopes, sync_status, webhook_enabled, provider_capabilities)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email, provider, access_token, refresh_token, token_expiry, status,
             reconnect_state, last_error, sync_checkpoint, metadata_json, now,
             auth_type, oauth_provider, token_scopes, sync_status, webhook_enabled, provider_capabilities)
        )

    def add_email(self, account_id: int, message_id: str, subject: str, sender: str, sender_email: str,
                  body_text: str = None, body_html: str = None, category: str = None,
                  confidence: float = None, priority: str = "Medium") -> int:
        return self.execute(
            """INSERT INTO emails (account_id, message_id, subject, sender, sender_email, body_text,
               body_html, category, confidence, priority, is_processed, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (account_id, message_id, subject, sender, sender_email, body_text, body_html,
             category, confidence, priority, datetime.now().isoformat())
        )

    def update_email_category(self, email_id: int, category: str, confidence: float):
        self.execute(
            "UPDATE emails SET category = ?, confidence = ?, is_processed = 1, processed_at = ? WHERE id = ?",
            (category, confidence, datetime.now().isoformat(), email_id)
        )

    @staticmethod
    def _sender_domain(sender_email: str) -> str:
        email = str(sender_email or "").strip().lower()
        if "@" not in email:
            return ""
        return email.rsplit("@", 1)[1]

    @staticmethod
    def _feedback_category(category: str) -> str:
        text = str(category or "").strip().lower()
        if text in {"scam", "fraud", "phishing", "malicious", "suspicious"}:
            return "Scam"
        if text in {"normal", "not scam", "safe", "legit", "legitimate", "trusted"}:
            return "Normal"
        return str(category or "").strip()

    def record_classification_override(self, email_id: int, category: str, user_id: int = 0) -> Optional[dict]:
        category = self._feedback_category(category)
        if category not in {"Scam", "Normal"}:
            return None

        email = self.fetch_one("SELECT id, sender_email FROM emails WHERE id = ?", (email_id,))
        if not email:
            return None

        sender_email = str(email.get("sender_email") or "").strip().lower()
        if not sender_email:
            return None

        if not user_id or not self.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)):
            user_id = self.add_user("local@aiemailorganizer.local", "local")

        sender_domain = self._sender_domain(sender_email)
        now = datetime.now().isoformat()
        self.execute(
            """
            INSERT INTO classification_overrides
                (user_id, sender_email, sender_domain, category, source_email_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, sender_email) DO UPDATE SET
                sender_domain = excluded.sender_domain,
                category = excluded.category,
                source_email_id = excluded.source_email_id,
                updated_at = excluded.updated_at
            """,
            (user_id, sender_email, sender_domain, category, email_id, now, now),
        )
        return self.get_classification_override(sender_email, user_id=user_id)

    def get_classification_override(self, sender_email: str, user_id: int = 0) -> Optional[dict]:
        sender_email = str(sender_email or "").strip().lower()
        if not sender_email:
            return None
        if user_id:
            row = self.fetch_one(
                """SELECT * FROM classification_overrides
                   WHERE user_id = ? AND sender_email = ?
                   ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (user_id, sender_email),
            )
            if row:
                return row
        return self.fetch_one(
            """SELECT * FROM classification_overrides
               WHERE sender_email = ?
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (sender_email,),
        )

    def list_classification_overrides(self, user_id: int = None, limit: int = 100) -> list:
        limit = min(max(int(limit or 100), 1), 1000)
        if user_id:
            return self.fetch_all(
                """SELECT * FROM classification_overrides
                   WHERE user_id = ?
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (user_id, limit),
            )
        return self.fetch_all(
            "SELECT * FROM classification_overrides ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    @staticmethod
    def _normalize_bucket_name(name: str, fallback: str = "General") -> str:
        text = display_bucket_name(name, fallback)
        return text[:80] or fallback

    def _bucket_scope_rows(self, table: str, account_id: int = None) -> list:
        if table not in {"mail_labels", "mail_folders"}:
            raise ValueError("Unsupported bucket table")
        if account_id is None:
            return self.fetch_all(f"SELECT * FROM {table} WHERE account_id IS NULL ORDER BY id")  # nosec B608
        return self.fetch_all(
            f"SELECT * FROM {table} WHERE account_id = ? OR account_id IS NULL ORDER BY CASE WHEN account_id = ? THEN 0 ELSE 1 END, id",  # nosec B608
            (account_id, account_id),
        )

    def _find_equivalent_bucket(self, table: str, account_id: int, name: str) -> Optional[dict]:
        wanted = canonical_bucket_key(name)
        if not wanted:
            return None
        for row in self._bucket_scope_rows(table, account_id):
            if canonical_bucket_key(row.get("name")) == wanted:
                return row
        return None

    def resolve_mail_label_name(self, account_id: int, name: str) -> str:
        existing = self._find_equivalent_bucket("mail_labels", account_id, name)
        return existing["name"] if existing else self._normalize_bucket_name(name)

    def resolve_mail_folder_name(self, account_id: int, name: str) -> str:
        existing = self._find_equivalent_bucket("mail_folders", account_id, name)
        return existing["name"] if existing else self._normalize_bucket_name(name, "INBOX")

    def ensure_mail_label(self, account_id: int, name: str) -> int:
        equivalent = self._find_equivalent_bucket("mail_labels", account_id, name)
        if equivalent:
            return equivalent["id"]
        label = self._normalize_bucket_name(name)
        existing = self.fetch_one(
            "SELECT id FROM mail_labels WHERE (account_id IS ? OR account_id = ?) AND name = ? ORDER BY id LIMIT 1",
            (account_id, account_id, label)
        )
        if existing:
            return existing["id"]
        return self.execute(
            "INSERT OR IGNORE INTO mail_labels (account_id, name) VALUES (?, ?)",
            (account_id, label)
        ) or (self.fetch_one("SELECT id FROM mail_labels WHERE account_id IS ? AND name = ?", (account_id, label)) or {}).get("id", 0)

    def ensure_mail_folder(self, account_id: int, name: str, metadata: Optional[dict] = None) -> int:
        equivalent = self._find_equivalent_bucket("mail_folders", account_id, name)
        if equivalent:
            return equivalent["id"]
        folder = self._normalize_bucket_name(name, "INBOX")
        existing = self.fetch_one(
            "SELECT id FROM mail_folders WHERE (account_id IS ? OR account_id = ?) AND name = ? ORDER BY id LIMIT 1",
            (account_id, account_id, folder)
        )
        if existing:
            return existing["id"]
        return self.execute(
            "INSERT OR IGNORE INTO mail_folders (account_id, name, metadata) VALUES (?, ?, ?)",
            (account_id, folder, json.dumps(metadata or {}, sort_keys=True))
        ) or (self.fetch_one("SELECT id FROM mail_folders WHERE account_id IS ? AND name = ?", (account_id, folder)) or {}).get("id", 0)

    def _email_label_list(self, email_id: int) -> list:
        email = self.fetch_one("SELECT labels FROM emails WHERE id = ?", (email_id,))
        if not email:
            return []
        raw = email.get("labels")
        if not raw:
            return []
        try:
            labels = json.loads(raw)
            return [str(item) for item in labels if str(item).strip()] if isinstance(labels, list) else []
        except (TypeError, json.JSONDecodeError):
            return [part.strip() for part in str(raw).split(",") if part.strip()]

    def add_email_label(self, email_id: int, label: str) -> bool:
        email = self.fetch_one("SELECT account_id FROM emails WHERE id = ?", (email_id,))
        if not email:
            return False
        account_id = email.get("account_id")
        bucket = self.resolve_mail_label_name(account_id, label)
        self.ensure_mail_label(account_id, bucket)
        self.execute(
            "INSERT OR IGNORE INTO email_labels (email_id, account_id, label) VALUES (?, ?, ?)",
            (email_id, account_id, bucket)
        )
        labels = sorted(set(self._email_label_list(email_id) + [bucket]))
        self.execute("UPDATE emails SET labels = ? WHERE id = ?", (json.dumps(labels), email_id))
        return True

    def set_email_folder(self, email_id: int, folder: str) -> bool:
        email = self.fetch_one("SELECT account_id FROM emails WHERE id = ?", (email_id,))
        if not email:
            return False
        bucket = self.resolve_mail_folder_name(email.get("account_id"), folder)
        self.ensure_mail_folder(email.get("account_id"), bucket)
        self.execute("UPDATE emails SET folder = ? WHERE id = ?", (bucket, email_id))
        return True

    def get_all_labels(self, account_id: int = None) -> list:
        if account_id is None:
            return self.fetch_all("SELECT * FROM mail_labels ORDER BY name ASC")
        return self.fetch_all("SELECT * FROM mail_labels WHERE account_id = ? OR account_id IS NULL ORDER BY name ASC", (account_id,))

    def get_all_folders(self, account_id: int = None) -> list:
        if account_id is None:
            return self.fetch_all("SELECT * FROM mail_folders ORDER BY name ASC")
        return self.fetch_all("SELECT * FROM mail_folders WHERE account_id = ? OR account_id IS NULL ORDER BY name ASC", (account_id,))

    def log_rule_action(self, email_id: int, rule_name: str, action_type: str, action_value,
                        local_success: bool, provider_success: bool, provider_status: str = None) -> int:
        return self.execute(
            """INSERT INTO rule_action_audit
               (email_id, rule_name, action_type, action_value, local_success, provider_success, provider_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (email_id, rule_name, action_type, json.dumps(action_value) if not isinstance(action_value, str) else action_value,
             1 if local_success else 0, 1 if provider_success else 0, provider_status)
        )

    def mark_email_forward_state(self, email_id: int, recipients, status: str, error: str = None) -> bool:
        recipients_json = json.dumps(recipients if isinstance(recipients, list) else [recipients])
        self.execute(
            """UPDATE emails
               SET forward_status = ?, forwarded_to = ?, forwarded_at = ?, forward_error = ?
               WHERE id = ?""",
            (status, recipients_json, datetime.now().isoformat(), error, email_id)
        )
        return True

    def log_email_forward(self, email_id: int, account_id: int, provider: str, rule_name: str,
                          recipients, cc=None, bcc=None, subject: str = None,
                          local_success: bool = True, provider_success: bool = False,
                          provider_status: str = None, metadata: dict = None) -> int:
        return self.execute(
            """INSERT INTO email_forward_audit
               (email_id, account_id, provider, rule_name, recipients, cc, bcc, subject,
                local_success, provider_success, provider_status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email_id,
                account_id,
                provider,
                rule_name,
                json.dumps(recipients if isinstance(recipients, list) else [recipients]),
                json.dumps(cc or []),
                json.dumps(bcc or []),
                subject,
                1 if local_success else 0,
                1 if provider_success else 0,
                provider_status,
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )

    def get_forward_audit(self, limit: int = 100) -> list:
        return self.fetch_all(
            "SELECT * FROM email_forward_audit ORDER BY created_at DESC, id DESC LIMIT ?",
            (min(max(int(limit or 100), 1), 1000),),
        )

    def _account_emails_for_user(self, user_id: int) -> set:
        rows = self.fetch_all("SELECT email FROM accounts WHERE user_id = ?", (user_id,))
        return {str(row.get("email") or "").strip().lower() for row in rows if row.get("email")}

    def upsert_forwarding_flow(self, account_id: int, provider: str, flow: dict) -> Optional[dict]:
        recipients = recipient_list(flow.get("to") or flow.get("recipients") or flow.get("forwardTo") or flow.get("forward_to"))
        if not recipients:
            return None
        condition = flow.get("condition") or flow.get("conditions") or flow.get("from") or flow.get("source") or "provider-forwarding"
        condition_sig = forwarding_condition_signature(condition)
        recipient_sig = recipients_signature(recipients)
        provider_rule_id = str(flow.get("id") or flow.get("provider_rule_id") or "").strip() or None
        now = datetime.now().isoformat()
        metadata = json.dumps(flow or {}, sort_keys=True, default=str)
        self.execute(
            """
            INSERT INTO mail_forwarding_flows
                (account_id, provider, provider_rule_id, condition_signature, recipients_signature, recipients, status, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'synced', ?, ?, ?)
            ON CONFLICT(account_id, condition_signature, recipients_signature) DO UPDATE SET
                provider = excluded.provider,
                provider_rule_id = COALESCE(excluded.provider_rule_id, mail_forwarding_flows.provider_rule_id),
                recipients = excluded.recipients,
                status = 'synced',
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (account_id, provider, provider_rule_id, condition_sig, recipient_sig, json.dumps(sorted(recipients)), metadata, now, now),
        )
        return self.find_existing_forwarding_flow(account_id, recipients, condition)

    def find_existing_forwarding_flow(self, account_id: int, recipients, condition) -> Optional[dict]:
        condition_sig = forwarding_condition_signature(condition)
        recipient_sig = recipients_signature(recipients)
        if not recipient_sig:
            return None
        return self.fetch_one(
            """SELECT * FROM mail_forwarding_flows
               WHERE account_id = ? AND condition_signature = ? AND recipients_signature = ?
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (account_id, condition_sig, recipient_sig),
        )

    def sync_existing_infrastructure(self, account_id: int, metadata: dict, provider: str = None) -> dict:
        metadata = metadata or {}
        summary = {"folders_synced": 0, "labels_synced": 0, "forwarding_synced": 0}

        for item in metadata.get("folders") or []:
            name = bucket_name_from_provider_item(item)
            if name:
                self.ensure_mail_folder(account_id, name, {"source": "provider_existing", "provider": provider, "raw": item})
                summary["folders_synced"] += 1

        for source_key in ("labels", "tags", "categories"):
            for item in metadata.get(source_key) or []:
                name = bucket_name_from_provider_item(item)
                if name:
                    self.ensure_mail_label(account_id, name)
                    summary["labels_synced"] += 1

        for item in metadata.get("forwarding_rules") or metadata.get("forwarding") or []:
            if isinstance(item, dict) and self.upsert_forwarding_flow(account_id, provider or "", item):
                summary["forwarding_synced"] += 1

        return summary

    def _existing_rule_id_for_signature(self, user_id: int, signature: str) -> Optional[int]:
        for row in self.fetch_all("SELECT id, condition, action FROM rules WHERE user_id = ? ORDER BY id", (user_id,)):
            try:
                _, _, existing_sig = canonical_rule_values(row.get("condition"), row.get("action"))
            except Exception:
                continue
            if existing_sig == signature:
                return row["id"]
        return None

    def _raise_if_forward_rule_is_duplicate_or_loop(self, user_id: int, condition: str, action: str) -> None:
        forwards = forwarding_actions(action)
        if not forwards:
            return
        account_rows = self.fetch_all("SELECT id, email FROM accounts WHERE user_id = ?", (user_id,))
        account_emails = {str(row.get("email") or "").strip().lower() for row in account_rows if row.get("email")}
        condition_payload = json.loads(condition or "{}")
        for forward in forwards:
            recipients = recipient_list(forward.get("value"))
            if account_emails.intersection(recipients):
                raise ValueError("Forwarding rule would create a recursive forwarding loop to the source account")
            for account in account_rows:
                if self.find_existing_forwarding_flow(account["id"], recipients, condition_payload):
                    raise ValueError("Forwarding rule duplicates an existing forwarding workflow synced from the mailbox")

    def add_rule(self, user_id: int, name: str, condition: str, action: str) -> int:
        condition, action, signature = canonical_rule_values(condition, action)
        existing_id = self._existing_rule_id_for_signature(user_id, signature)
        if existing_id:
            return existing_id
        self._raise_if_forward_rule_is_duplicate_or_loop(user_id, condition, action)
        return self.execute(
            "INSERT INTO rules (user_id, name, condition, action) VALUES (?, ?, ?, ?)",
            (user_id, name, condition, action)
        )

    def add_feedback(self, email_id: int, predicted_category: str, actual_category: str, user_id: int) -> int:
        return self.execute(
            "INSERT INTO feedback (email_id, predicted_category, actual_category, user_id) VALUES (?, ?, ?, ?)",
            (email_id, predicted_category, actual_category, user_id)
        )

    def get_user_by_email(self, email: str) -> Optional[dict]:
        return self.fetch_one("SELECT * FROM users WHERE email = ?", (email,))

    def get_account_by_email(self, email: str) -> Optional[dict]:
        return self.fetch_one("SELECT * FROM accounts WHERE email = ?", (email,))

    def get_account_by_id(self, account_id: int) -> Optional[dict]:
        return self.fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def get_emails_by_category(self, category: str, limit: int = 100) -> list:
        return self.fetch_all(
            "SELECT * FROM emails WHERE category = ? ORDER BY created_at DESC LIMIT ?",
            (category, limit)
        )

    def get_all_categories(self) -> list:
        return self.fetch_all("SELECT DISTINCT category FROM emails WHERE category IS NOT NULL")

    def get_rules_by_user(self, user_id: int) -> list:
        return self.fetch_all("SELECT * FROM rules WHERE user_id = ? AND is_active = 1", (user_id,))

    def get_accounts_by_user(self, user_id: int) -> list:
        return self.fetch_all("SELECT * FROM accounts WHERE user_id = ?", (user_id,))

    def get_all_accounts(self) -> list:
        return self.fetch_all("SELECT * FROM accounts ORDER BY created_at DESC")

    def delete_account(self, account_id: int) -> bool:
        self.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return True

    def update_account_tokens(self, account_id: int, access_token: str, refresh_token: str, expiry: str) -> bool:
        self.execute(
            """UPDATE accounts
               SET access_token = ?, refresh_token = COALESCE(?, refresh_token), token_expiry = ?,
                   status = 'connected', reconnect_state = 'ok', last_error = NULL, sync_status = 'active', updated_at = ?
               WHERE id = ?""",
            (access_token, refresh_token, expiry, datetime.now().isoformat(), account_id)
        )
        return True

    def update_account_status(self, account_id: int, status: str, reconnect_state: str = None,
                              last_error: str = None) -> bool:
        query = "UPDATE accounts SET status = ?, updated_at = ?"
        params = [status, datetime.now().isoformat()]
        if reconnect_state is not None:
            query += ", reconnect_state = ?"
            params.append(reconnect_state)
        if last_error is not None:
            query += ", last_error = ?"
            params.append(last_error)
        query += " WHERE id = ?"
        params.append(account_id)
        self.execute(query, tuple(params))
        return True

    def update_account_metadata(self, account_id: int, metadata: dict = None,
                                sync_checkpoint: str = None, last_sync_at: str = None) -> bool:
        account = self.get_account_by_id(account_id)
        if not account:
            return False

        current = {}
        if account.get("metadata"):
            try:
                current = json.loads(account["metadata"])
            except (TypeError, json.JSONDecodeError):
                current = {}
        if metadata:
            current.update(metadata)

        query = "UPDATE accounts SET metadata = ?, updated_at = ?"
        params = [json.dumps(current, sort_keys=True), datetime.now().isoformat()]
        if sync_checkpoint is not None:
            query += ", sync_checkpoint = ?"
            params.append(sync_checkpoint)
        if last_sync_at is not None:
            query += ", last_sync_at = ?"
            params.append(last_sync_at)
        query += " WHERE id = ?"
        params.append(account_id)
        self.execute(query, tuple(params))
        return True

    def add_provider_diagnostic(self, account_id: int, provider: str, status: str, detail: dict) -> int:
        return self.execute(
            "INSERT INTO provider_diagnostics (account_id, provider, status, detail) VALUES (?, ?, ?, ?)",
            (account_id, provider, status, json.dumps(detail or {}, sort_keys=True))
        )

    def get_latest_provider_diagnostic(self, account_id: int) -> Optional[dict]:
        return self.fetch_one(
            "SELECT * FROM provider_diagnostics WHERE account_id = ? ORDER BY checked_at DESC LIMIT 1",
            (account_id,)
        )

    def add_sync_status(self, account_id: int, status: str) -> int:
        return self.execute(
            "INSERT INTO sync_status (account_id, status) VALUES (?, ?)",
            (account_id, status)
        )

    def update_sync_status(self, sync_id: int, status: str, progress: int = None, 
                          processed_emails: int = None, total_emails: int = None, 
                          error: str = None) -> bool:
        query = "UPDATE sync_status SET status = ?"
        params = [status]
        if progress is not None:
            query += ", progress = ?"
            params.append(progress)
        if processed_emails is not None:
            query += ", processed_emails = ?"
            params.append(processed_emails)
        if total_emails is not None:
            query += ", total_emails = ?"
            params.append(total_emails)
        if error is not None:
            query += ", last_error = ?"
            params.append(error)
        if status in ("completed", "failed", "cancelled"):
            query += ", completed_at = ?"
            params.append(datetime.now().isoformat())
        query += " WHERE id = ?"
        params.append(sync_id)
        self.execute(query, tuple(params))
        return True

    def create_oauth_state(self, provider: str, state: str, code_verifier: str,
                           redirect_uri: str, expires_at: str) -> int:
        self.cleanup_oauth_states()
        return self.execute(
            """INSERT INTO oauth_states (provider, state, code_verifier, redirect_uri, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (provider, state, code_verifier, redirect_uri, expires_at)
        )

    def consume_oauth_state(self, provider: str, state: str) -> Optional[dict]:
        now = datetime.now(timezone.utc).isoformat()
        row = self.fetch_one(
            """SELECT * FROM oauth_states
               WHERE provider = ? AND state = ? AND consumed_at IS NULL AND expires_at > ?""",
            (provider, state, now)
        )
        if not row:
            return None

        self.execute(
            "UPDATE oauth_states SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
            (now, row["id"])
        )
        return row

    def cleanup_oauth_states(self):
        self.execute(
            "DELETE FROM oauth_states WHERE consumed_at IS NOT NULL OR expires_at <= ?",
            (datetime.now(timezone.utc).isoformat(),)
        )

    def get_active_sync(self, account_id: int) -> Optional[dict]:
        return self.fetch_one(
            "SELECT * FROM sync_status WHERE account_id = ? AND status IN ('pending', 'in_progress') ORDER BY started_at DESC LIMIT 1",
            (account_id,)
        )

    def get_feedback_count(self) -> Optional[dict]:
        return self.fetch_one("SELECT COUNT(*) as count FROM feedback")

    def get_connection_status(self) -> dict:
        """Get database connection status"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("PRAGMA journal_mode")
                journal = cursor.fetchone()[0]
                cursor.execute("PRAGMA page_count")
                pages = cursor.fetchone()[0]
                cursor.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                
                return {
                    "status": "healthy",
                    "journal_mode": journal,
                    "size_bytes": pages * page_size,
                    "path": self.db_path
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def close(self):
        """Close the current thread connection; use close_all_instances on app shutdown."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None
                self._unregister_connection(conn)
                self._pragmas_applied = False


atexit.register(Database.close_all_instances)
