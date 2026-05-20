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
        self._ensure_column(cursor, "accounts", "display_name", "TEXT")
        self._ensure_column(cursor, "accounts", "email_address", "TEXT")
        self._ensure_column(cursor, "accounts", "sync_enabled", "INTEGER DEFAULT 1")
        self._ensure_column(cursor, "accounts", "structure_sync_status", "TEXT DEFAULT 'pending'")
        self._ensure_column(cursor, "accounts", "structure_synced_at", "TIMESTAMP")
        self._ensure_column(cursor, "accounts", "structure_sync_error", "TEXT")

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
        self._ensure_column(cursor, "emails", "mailbox_id", "INTEGER")
        self._ensure_column(cursor, "emails", "provider", "TEXT")
        self._ensure_column(cursor, "emails", "email_address", "TEXT")
        self._ensure_column(cursor, "emails", "provider_message_id", "TEXT")
        self._ensure_column(cursor, "emails", "thread_id", "TEXT")
        self._ensure_column(cursor, "emails", "conversation_id", "TEXT")
        self._ensure_column(cursor, "emails", "recipients", "TEXT")
        self._ensure_column(cursor, "emails", "date", "TEXT")
        self._ensure_column(cursor, "emails", "snippet", "TEXT")
        self._ensure_column(cursor, "emails", "is_starred", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "emails", "last_synced_at", "TIMESTAMP")
        self._ensure_column(cursor, "emails", "cc", "TEXT")
        self._ensure_column(cursor, "emails", "bcc", "TEXT")
        self._ensure_column(cursor, "emails", "reply_to", "TEXT")
        self._ensure_column(cursor, "emails", "headers", "TEXT")
        self._ensure_column(cursor, "emails", "message_search_text", "TEXT")
        self._ensure_column(cursor, "emails", "attachment_text", "TEXT")
        self._ensure_column(cursor, "emails", "attachment_ocr_text", "TEXT")
        self._ensure_column(cursor, "emails", "scan_status", "TEXT")
        self._ensure_column(cursor, "emails", "scan_error", "TEXT")
        self._ensure_column(cursor, "emails", "last_scanned_at", "TIMESTAMP")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, name)
            )
        """)
        self._ensure_column(cursor, "mail_labels", "mailbox_id", "INTEGER")
        self._ensure_column(cursor, "mail_labels", "provider", "TEXT")
        self._ensure_column(cursor, "mail_labels", "email_address", "TEXT")
        self._ensure_column(cursor, "mail_labels", "provider_label_id", "TEXT")
        self._ensure_column(cursor, "mail_labels", "color", "TEXT")
        self._ensure_column(cursor, "mail_labels", "created_locally", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "mail_labels", "synced_to_provider", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "mail_labels", "last_synced_at", "TIMESTAMP")
        self._ensure_column(cursor, "mail_labels", "label_type", "TEXT DEFAULT 'custom'")

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
        self._ensure_column(cursor, "mail_folders", "mailbox_id", "INTEGER")
        self._ensure_column(cursor, "mail_folders", "provider", "TEXT")
        self._ensure_column(cursor, "mail_folders", "email_address", "TEXT")
        self._ensure_column(cursor, "mail_folders", "provider_folder_id", "TEXT")
        self._ensure_column(cursor, "mail_folders", "folder_type", "TEXT DEFAULT 'custom'")
        self._ensure_column(cursor, "mail_folders", "parent_folder_id", "TEXT")
        self._ensure_column(cursor, "mail_folders", "created_locally", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "mail_folders", "synced_to_provider", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "mail_folders", "last_synced_at", "TIMESTAMP")
        self._ensure_column(cursor, "mail_folders", "folder_path", "TEXT")

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
        self._ensure_column(cursor, "rules", "description", "TEXT")
        self._ensure_column(cursor, "rules", "status", "TEXT DEFAULT 'active'")
        self._ensure_column(cursor, "rules", "mailbox_scope", "TEXT DEFAULT 'all'")
        self._ensure_column(cursor, "rules", "mailbox_id", "INTEGER")
        self._ensure_column(cursor, "rules", "scan_scope", "TEXT DEFAULT 'entire_email_with_attachments'")
        self._ensure_column(cursor, "rules", "match_mode", "TEXT DEFAULT 'any'")
        self._ensure_column(cursor, "rules", "priority", "TEXT DEFAULT 'Medium'")
        self._ensure_column(cursor, "rules", "stop_processing", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "rules", "is_sample", "INTEGER DEFAULT 0")
        self._ensure_column(cursor, "rules", "created_by", "INTEGER")
        self._ensure_column(cursor, "rules", "updated_at", "TIMESTAMP")
        self._ensure_column(cursor, "rules", "last_run_at", "TIMESTAMP")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rule_execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER,
                rule_name TEXT,
                mailbox_id INTEGER,
                message_id INTEGER,
                matched INTEGER DEFAULT 0,
                matched_condition TEXT,
                matched_source TEXT,
                matched_text_preview TEXT,
                action_taken TEXT,
                provider_status TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rule_execution_logs_rule ON rule_execution_logs(rule_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rule_execution_logs_mailbox ON rule_execution_logs(mailbox_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rule_execution_logs_message ON rule_execution_logs(message_id)")
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_mailbox_provider_message ON emails(mailbox_id, provider_message_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_provider_email ON emails(provider, email_address)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_labels_mailbox ON mail_labels(mailbox_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mail_folders_mailbox ON mail_folders(mailbox_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
        self._safe_index(cursor, "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_provider_email_unique ON accounts(provider, email)")
        self._safe_index(cursor, "CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_mailbox_message_unique ON emails(mailbox_id, provider_message_id)")
        self._safe_index(cursor, "CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_folders_mailbox_provider_id_unique ON mail_folders(mailbox_id, provider_folder_id)")
        self._safe_index(cursor, "CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_labels_mailbox_provider_id_unique ON mail_labels(mailbox_id, provider_label_id)")
        
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
        self._ensure_column(cursor, "oauth_states", "requested_email", "TEXT")
        self._ensure_column(cursor, "oauth_states", "oauth_config_provider", "TEXT")
        self._ensure_column(cursor, "oauth_states", "oauth_config_email", "TEXT")
        self._ensure_column(cursor, "oauth_states", "redirect_after_callback", "TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_oauth_states_provider_state ON oauth_states(provider, state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_oauth_states_config ON oauth_states(oauth_config_provider, oauth_config_email)")

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
        self._backfill_mailbox_columns(cursor)
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        conn.commit()
        conn.close()

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _safe_index(self, cursor: sqlite3.Cursor, sql: str):
        try:
            cursor.execute(sql)
        except sqlite3.Error:
            # Existing customer databases may contain legacy duplicates. Keep
            # startup safe; runtime upserts still enforce mailbox scoping.
            pass

    def _backfill_mailbox_columns(self, cursor: sqlite3.Cursor):
        now = datetime.now().isoformat()
        cursor.execute("UPDATE accounts SET email_address = LOWER(TRIM(email)) WHERE email_address IS NULL OR email_address = ''")
        cursor.execute("UPDATE accounts SET sync_enabled = 1 WHERE sync_enabled IS NULL")
        cursor.execute("""
            UPDATE emails
            SET mailbox_id = account_id
            WHERE mailbox_id IS NULL AND account_id IS NOT NULL
        """)
        cursor.execute("""
            UPDATE emails
            SET provider = (SELECT provider FROM accounts WHERE accounts.id = emails.account_id)
            WHERE provider IS NULL OR provider = ''
        """)
        cursor.execute("""
            UPDATE emails
            SET email_address = (SELECT email FROM accounts WHERE accounts.id = emails.account_id)
            WHERE email_address IS NULL OR email_address = ''
        """)
        cursor.execute("UPDATE emails SET provider_message_id = message_id WHERE provider_message_id IS NULL OR provider_message_id = ''")
        cursor.execute("UPDATE emails SET snippet = SUBSTR(COALESCE(body_text, ''), 1, 240) WHERE snippet IS NULL")
        cursor.execute("UPDATE emails SET last_synced_at = COALESCE(processed_at, created_at, ?) WHERE last_synced_at IS NULL", (now,))
        for table in ("mail_labels", "mail_folders"):
            cursor.execute(f"UPDATE {table} SET mailbox_id = account_id WHERE mailbox_id IS NULL AND account_id IS NOT NULL")
            cursor.execute(f"""
                UPDATE {table}
                SET provider = (SELECT provider FROM accounts WHERE accounts.id = {table}.account_id)
                WHERE provider IS NULL OR provider = ''
            """)
            cursor.execute(f"""
                UPDATE {table}
                SET email_address = (SELECT email FROM accounts WHERE accounts.id = {table}.account_id)
                WHERE email_address IS NULL OR email_address = ''
            """)

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
                    last_error = ?, email_address = ?
            """
            params = [user_id, status, reconnect_state, metadata_json, now, last_error, email]

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
                auth_type, oauth_provider, token_scopes, sync_status, webhook_enabled, provider_capabilities,
                email_address, sync_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email, provider, access_token, refresh_token, token_expiry, status,
             reconnect_state, last_error, sync_checkpoint, metadata_json, now,
             auth_type, oauth_provider, token_scopes, sync_status, webhook_enabled, provider_capabilities,
             email, 1)
        )

    def add_email(self, account_id: int, message_id: str, subject: str, sender: str, sender_email: str,
                  body_text: str = None, body_html: str = None, category: str = None,
                  confidence: float = None, priority: str = "Medium", provider_message_id: str = None,
                  thread_id: str = None, conversation_id: str = None, recipients=None, date: str = None,
                  snippet: str = None, is_read: int = 0, is_starred: int = 0, folder: str = None,
                  labels=None) -> int:
        account = self.get_account_by_id(account_id) or {}
        provider = account.get("provider")
        email_address = account.get("email")
        provider_message_id = provider_message_id or message_id
        if recipients is not None and not isinstance(recipients, str):
            recipients = json.dumps(recipients, sort_keys=True)
        if labels is not None and not isinstance(labels, str):
            labels = json.dumps(labels)
        labels = labels if labels is not None else "[]"
        folder = folder or "INBOX"
        snippet = snippet if snippet is not None else (body_text or "")[:240]
        now = datetime.now().isoformat()
        return self.execute(
            """INSERT INTO emails (account_id, message_id, subject, sender, sender_email, body_text,
               body_html, category, confidence, priority, is_read, is_processed, processed_at,
               folder, labels, mailbox_id, provider, email_address, provider_message_id, thread_id,
               conversation_id, recipients, date, snippet, is_starred, last_synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, message_id, subject, sender, sender_email, body_text, body_html,
             category, confidence, priority, int(bool(is_read)), now, folder, labels, account_id,
             provider, email_address, provider_message_id, thread_id, conversation_id, recipients,
             date, snippet, int(bool(is_starred)), now)
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

    def _mailbox_scope(self, account_id: int) -> dict:
        account = self.get_account_by_id(account_id) if account_id is not None else None
        return {
            "mailbox_id": account_id,
            "provider": (account or {}).get("provider"),
            "email_address": (account or {}).get("email"),
        }

    @staticmethod
    def _provider_item_id(item: dict, *keys: str) -> Optional[str]:
        if not isinstance(item, dict):
            return None
        for key in keys:
            value = item.get(key)
            if value:
                return str(value)
        return None

    def ensure_mail_label(self, account_id: int, name: str, provider_label_id: str = None,
                          color: str = None, created_locally: bool = False,
                          synced_to_provider: bool = False, label_type: str = None) -> int:
        equivalent = self._find_equivalent_bucket("mail_labels", account_id, name)
        if equivalent:
            updates = []
            params = []
            if provider_label_id and not equivalent.get("provider_label_id"):
                updates.append("provider_label_id = ?")
                params.append(provider_label_id)
            if color and not equivalent.get("color"):
                updates.append("color = ?")
                params.append(color)
            if label_type and not equivalent.get("label_type"):
                updates.append("label_type = ?")
                params.append(label_type)
            if created_locally:
                updates.append("created_locally = 1")
            if synced_to_provider:
                updates.append("synced_to_provider = 1")
                updates.append("last_synced_at = ?")
                params.append(datetime.now().isoformat())
            scope = self._mailbox_scope(account_id)
            if scope["mailbox_id"] and not equivalent.get("mailbox_id"):
                updates.extend(["mailbox_id = ?", "provider = ?", "email_address = ?"])
                params.extend([scope["mailbox_id"], scope["provider"], scope["email_address"]])
            if updates:
                params.append(equivalent["id"])
                self.execute(f"UPDATE mail_labels SET {', '.join(updates)} WHERE id = ?", tuple(params))
            return equivalent["id"]
        label = self._normalize_bucket_name(name)
        existing = self.fetch_one(
            "SELECT id FROM mail_labels WHERE (account_id IS ? OR account_id = ?) AND name = ? ORDER BY id LIMIT 1",
            (account_id, account_id, label)
        )
        if existing:
            return existing["id"]
        scope = self._mailbox_scope(account_id)
        synced_at = datetime.now().isoformat() if synced_to_provider else None
        return self.execute(
            """INSERT OR IGNORE INTO mail_labels
               (account_id, mailbox_id, provider, email_address, name, provider_label_id, color,
                created_locally, synced_to_provider, last_synced_at, label_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, scope["mailbox_id"], scope["provider"], scope["email_address"], label,
             provider_label_id, color, 1 if created_locally else 0,
             1 if synced_to_provider else 0, synced_at, label_type or "custom")
        ) or (self.fetch_one("SELECT id FROM mail_labels WHERE account_id IS ? AND name = ?", (account_id, label)) or {}).get("id", 0)

    def ensure_mail_folder(self, account_id: int, name: str, metadata: Optional[dict] = None,
                           provider_folder_id: str = None, folder_type: str = "custom",
                           parent_folder_id: str = None, created_locally: bool = False,
                           synced_to_provider: bool = False, folder_path: str = None) -> int:
        equivalent = self._find_equivalent_bucket("mail_folders", account_id, name)
        if equivalent:
            updates = []
            params = []
            if provider_folder_id and not equivalent.get("provider_folder_id"):
                updates.append("provider_folder_id = ?")
                params.append(provider_folder_id)
            if folder_type and not equivalent.get("folder_type"):
                updates.append("folder_type = ?")
                params.append(folder_type)
            if parent_folder_id and not equivalent.get("parent_folder_id"):
                updates.append("parent_folder_id = ?")
                params.append(parent_folder_id)
            if folder_path and not equivalent.get("folder_path"):
                updates.append("folder_path = ?")
                params.append(folder_path)
            if metadata:
                updates.append("metadata = ?")
                params.append(json.dumps(metadata or {}, sort_keys=True))
            if created_locally:
                updates.append("created_locally = 1")
            if synced_to_provider:
                updates.append("synced_to_provider = 1")
                updates.append("last_synced_at = ?")
                params.append(datetime.now().isoformat())
            scope = self._mailbox_scope(account_id)
            if scope["mailbox_id"] and not equivalent.get("mailbox_id"):
                updates.extend(["mailbox_id = ?", "provider = ?", "email_address = ?"])
                params.extend([scope["mailbox_id"], scope["provider"], scope["email_address"]])
            if updates:
                params.append(equivalent["id"])
                self.execute(f"UPDATE mail_folders SET {', '.join(updates)} WHERE id = ?", tuple(params))
            return equivalent["id"]
        folder = self._normalize_bucket_name(name, "INBOX")
        existing = self.fetch_one(
            "SELECT id FROM mail_folders WHERE (account_id IS ? OR account_id = ?) AND name = ? ORDER BY id LIMIT 1",
            (account_id, account_id, folder)
        )
        if existing:
            return existing["id"]
        scope = self._mailbox_scope(account_id)
        synced_at = datetime.now().isoformat() if synced_to_provider else None
        return self.execute(
            """INSERT OR IGNORE INTO mail_folders
               (account_id, mailbox_id, provider, email_address, name, metadata, provider_folder_id,
                folder_type, parent_folder_id, created_locally, synced_to_provider, last_synced_at, folder_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, scope["mailbox_id"], scope["provider"], scope["email_address"], folder,
             json.dumps(metadata or {}, sort_keys=True), provider_folder_id, folder_type,
             parent_folder_id, 1 if created_locally else 0, 1 if synced_to_provider else 0, synced_at,
             folder_path or folder)
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

    def get_all_labels(self, account_id: int = None, include_shared: bool = True) -> list:
        if account_id is None:
            return self.fetch_all("SELECT * FROM mail_labels ORDER BY name ASC")
        if not include_shared:
            return self.fetch_all("SELECT * FROM mail_labels WHERE account_id = ? OR mailbox_id = ? ORDER BY name ASC", (account_id, account_id))
        return self.fetch_all("SELECT * FROM mail_labels WHERE account_id = ? OR account_id IS NULL ORDER BY name ASC", (account_id,))

    def get_all_folders(self, account_id: int = None, include_shared: bool = True) -> list:
        if account_id is None:
            return self.fetch_all("SELECT * FROM mail_folders ORDER BY name ASC")
        if not include_shared:
            return self.fetch_all("SELECT * FROM mail_folders WHERE account_id = ? OR mailbox_id = ? ORDER BY name ASC", (account_id, account_id))
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

    def log_rule_execution(self, rule_id: int = None, rule_name: str = None, mailbox_id: int = None,
                           message_id: int = None, matched: bool = False, matched_condition: str = None,
                           matched_source: str = None, matched_text_preview: str = None,
                           action_taken: str = None, provider_status: str = None,
                           error: str = None) -> int:
        return self.execute(
            """INSERT INTO rule_execution_logs
               (rule_id, rule_name, mailbox_id, message_id, matched, matched_condition,
                matched_source, matched_text_preview, action_taken, provider_status, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule_id,
                rule_name,
                mailbox_id,
                message_id,
                1 if matched else 0,
                matched_condition,
                matched_source,
                (matched_text_preview or "")[:240],
                action_taken,
                provider_status,
                error,
            ),
        )

    def update_email_scan_index(self, email_id: int, search_text: str = None,
                                attachment_text: str = None, attachment_ocr_text: str = None,
                                status: str = "indexed", error: str = None) -> bool:
        self.execute(
            """UPDATE emails
               SET message_search_text = ?, attachment_text = ?, attachment_ocr_text = ?,
                   scan_status = ?, scan_error = ?, last_scanned_at = ?
               WHERE id = ?""",
            (
                search_text,
                attachment_text,
                attachment_ocr_text,
                status,
                error,
                datetime.now().isoformat(),
                email_id,
            ),
        )
        return True

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
                self.ensure_mail_folder(
                    account_id,
                    name,
                    {"source": "provider_existing", "provider": provider, "raw": item},
                    provider_folder_id=self._provider_item_id(item, "id", "path", "name"),
                    folder_type="system" if isinstance(item, dict) and item.get("type") == "system" else "custom",
                    synced_to_provider=True,
                )
                summary["folders_synced"] += 1

        for source_key in ("labels", "tags", "categories"):
            for item in metadata.get(source_key) or []:
                name = bucket_name_from_provider_item(item)
                if name:
                    self.ensure_mail_label(
                        account_id,
                        name,
                        provider_label_id=self._provider_item_id(item, "id", "name", "displayName"),
                        color=(item or {}).get("color") if isinstance(item, dict) else None,
                        synced_to_provider=True,
                    )
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

    def add_rule(self, user_id: int, name: str, condition: str, action: str,
                 description: str = "", status: str = "active", mailbox_scope: str = "all",
                 mailbox_id: int = None, scan_scope: str = "entire_email_with_attachments",
                 match_mode: str = "any", priority: str = "Medium",
                 stop_processing: bool = False, is_sample: bool = False,
                 created_by: int = None) -> int:
        condition, action, signature = canonical_rule_values(condition, action)
        existing_id = self._existing_rule_id_for_signature(user_id, signature)
        if existing_id:
            self.execute(
                """UPDATE rules
                   SET name = ?, description = ?, status = ?, mailbox_scope = ?, mailbox_id = ?,
                       scan_scope = ?, match_mode = ?, priority = ?, stop_processing = ?,
                       is_sample = ?, created_by = COALESCE(created_by, ?), updated_at = ?
                   WHERE id = ?""",
                (
                    name,
                    description,
                    status,
                    mailbox_scope or "all",
                    mailbox_id,
                    scan_scope or "entire_email_with_attachments",
                    match_mode or "any",
                    priority or "Medium",
                    1 if stop_processing else 0,
                    1 if is_sample else 0,
                    created_by,
                    datetime.now().isoformat(),
                    existing_id,
                ),
            )
            return existing_id
        self._raise_if_forward_rule_is_duplicate_or_loop(user_id, condition, action)
        return self.execute(
            """INSERT INTO rules
               (user_id, name, condition, action, description, status, mailbox_scope, mailbox_id,
                scan_scope, match_mode, priority, stop_processing, is_sample, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                name,
                condition,
                action,
                description,
                status,
                mailbox_scope or "all",
                mailbox_id,
                scan_scope or "entire_email_with_attachments",
                match_mode or "any",
                priority or "Medium",
                1 if stop_processing else 0,
                1 if is_sample else 0,
                created_by,
                datetime.now().isoformat(),
            )
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

    def get_account_by_provider_email(self, provider: str, email: str) -> Optional[dict]:
        return self.fetch_one(
            "SELECT * FROM accounts WHERE provider = ? AND email = ? ORDER BY id LIMIT 1",
            ((provider or "").strip().lower(), (email or "").strip().lower()),
        )

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
        return self.fetch_all(
            "SELECT * FROM rules WHERE user_id = ? AND is_active = 1 AND COALESCE(is_sample, 0) = 0",
            (user_id,),
        )

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

    def update_mailbox_structure_status(self, account_id: int, status: str,
                                        error: str = None, synced_at: str = None) -> bool:
        if synced_at is None and status == "synced":
            synced_at = datetime.now().isoformat()
        self.execute(
            """UPDATE accounts
               SET structure_sync_status = ?, structure_sync_error = ?,
                   structure_synced_at = COALESCE(?, structure_synced_at), updated_at = ?
               WHERE id = ?""",
            (status, error, synced_at, datetime.now().isoformat(), account_id),
        )
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
                           redirect_uri: str, expires_at: str, requested_email: str = None,
                           oauth_config_provider: str = None, oauth_config_email: str = None,
                           redirect_after_callback: str = None) -> int:
        self.cleanup_oauth_states()
        requested_email = (requested_email or "").strip().lower() or None
        oauth_config_provider = (oauth_config_provider or provider or "").strip().lower() or None
        oauth_config_email = (oauth_config_email or "").strip().lower() or None
        return self.execute(
            """INSERT INTO oauth_states
               (provider, state, code_verifier, redirect_uri, expires_at, requested_email,
                oauth_config_provider, oauth_config_email, redirect_after_callback)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider, state, code_verifier, redirect_uri, expires_at, requested_email,
             oauth_config_provider, oauth_config_email, redirect_after_callback)
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
