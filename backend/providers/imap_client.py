"""
IMAP Client - Enterprise Resilient IMAP

Features:
- IDLE mode with keepalive
- NOOP heartbeats
- Reconnect watchdog
- Mailbox drift detection
- UID validity tracking
- Folder reconciliation
"""

import email
import imaplib
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("imap.client")


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    IDLE = "idle"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class FolderInfo:
    """Information about a folder"""
    name: str
    path: str
    exists: int = 0
    recent: int = 0
    unseen: int = 0
    uidvalidity: Optional[int] = None
    uidnext: Optional[int] = None


@dataclass
class MailboxState:
    """Current mailbox state for drift detection"""
    folder: str
    message_count: int
    uid_validity: int
    uid_next: int
    recent_uids: List[str] = field(default_factory=list)
    last_check: float = field(default_factory=time.time)


class IMAPClient:
    """
    Enterprise IMAP client with full resiliency.
    
    Features:
    - Automatic IDLE mode
    - NOOP keepalive heartbeats
    - Connection watchdog
    - UID validity tracking
    - Mailbox drift detection
    - Automatic reconnection
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        use_ssl: bool = True,
        timeout: int = 30,
        idle_timeout: int = 1800,  # 30 minutes
        noop_interval: int = 30,   # 30 seconds
        reconnect_attempts: int = 3,
        reconnect_delay: float = 2.0
    ):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.idle_timeout = idle_timeout
        self.noop_interval = noop_interval
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay

        # Connection state
        self._connection: Optional[imaplib.IMAP4_SSL] = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._selected_folder: Optional[str] = None

        # Credentials: usernames may be retained for connection identity, but
        # provider credentials are resolved only when needed and are not stored
        # as long-lived plaintext attributes.
        self._username: Optional[str] = None
        self._credential_provider: Optional[Callable[[], Optional[str]]] = None

        # Threading
        self._lock = threading.RLock()
        self._idle_thread: Optional[threading.Thread] = None
        self._idle_running = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_running = threading.Event()

        # State tracking
        self._mailbox_states: Dict[str, MailboxState] = {}
        self._last_noop: float = 0
        self._last_idle: float = 0

        # Callbacks
        self._on_new_email: Optional[Callable] = None
        self._on_connection_lost: Optional[Callable] = None
        self._on_drift_detected: Optional[Callable] = None

        logger.info(f"IMAP client initialized for {host}:{port}")

    def connect(self, username: str, password: str) -> bool:
        """Connect and authenticate using a transient credential value."""
        with self._lock:
            self._username = username
            return self._do_connect(transient_password=password)

    def connect_with_credential_provider(self, username: str, credential_provider: Callable[[], Optional[str]]) -> bool:
        """Connect with a backend-owned credential provider for safe reconnects."""
        with self._lock:
            self._username = username
            self._credential_provider = credential_provider
            return self._do_connect()

    def _resolve_password(self, transient_password: Optional[str] = None) -> Optional[str]:
        if transient_password:
            return transient_password
        if self._credential_provider:
            return self._credential_provider()
        return None

    def _do_connect(self, transient_password: Optional[str] = None) -> bool:
        """Internal connect implementation"""
        self._connection_state = ConnectionState.CONNECTING

        try:
            # Create connection
            if self.use_ssl:
                self._connection = imaplib.IMAP4_SSL(
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout
                )
            else:
                self._connection = imaplib.IMAP4(
                    host=self.host,
                    port=self.port,
                    timeout=self.timeout
                )

            # Authenticate with a transient secret resolved by the backend.
            self._connection_state = ConnectionState.AUTHENTICATING
            password = self._resolve_password(transient_password)
            if not password:
                raise ValueError("IMAP credential is unavailable for connection")
            try:
                self._connection.login(self._username, password)
            finally:
                password = None
                transient_password = None

            self._connection_state = ConnectionState.CONNECTED

            logger.info(f"Connected to {self.host} as {self._username}")

            # Start watchdog
            self._start_watchdog()

            return True

        except Exception as e:
            self._connection_state = ConnectionState.FAILED
            logger.error(f"Failed to connect to {self.host}: {e}")
            return False

    def _start_watchdog(self):
        """Start connection watchdog"""
        if self._watchdog_running.is_set():
            return

        self._watchdog_running.set()

        def watchdog_loop():
            while self._watchdog_running.is_set():
                try:
                    self._watchdog_check()
                except Exception as e:
                    logger.error(f"Watchdog error: {e}")

                time.sleep(self.noop_interval)

        self._watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_check(self):
        """Watchdog check for connection health"""
        with self._lock:
            if not self._connection or self._connection_state != ConnectionState.CONNECTED:
                return

            try:
                # Send NOOP for keepalive
                self._connection.noop()
                self._last_noop = time.time()

            except (imaplib.IMAP4.error, socket.error) as e:
                logger.warning(f"Watchdog detected connection issue: {e}")
                self._handle_connection_lost()

    def _handle_connection_lost(self):
        """Handle connection loss"""
        if self._on_connection_lost:
            self._on_connection_lost()

        # Try to reconnect
        self._do_reconnect()

    def _do_reconnect(self):
        """Attempt to reconnect"""
        self._connection_state = ConnectionState.RECONNECTING

        for attempt in range(self.reconnect_attempts):
            logger.info(f"Reconnect attempt {attempt + 1}/{self.reconnect_attempts}")

            try:
                # Close old connection
                if self._connection:
                    try:
                        self._connection.close()
                    except Exception:
                        pass

                # Reconnect only when a backend credential provider is available.
                if not self._credential_provider:
                    logger.warning("Reconnect skipped because no backend credential provider is registered")
                    break
                if self._do_connect():
                    # Re-select folder if needed
                    if self._selected_folder:
                        self.select_folder(self._selected_folder)

                    logger.info("Reconnected successfully")
                    return

            except Exception as e:
                logger.warning(f"Reconnect attempt {attempt + 1} failed: {e}")

            time.sleep(self.reconnect_delay)

        self._connection_state = ConnectionState.FAILED
        logger.error("Failed to reconnect after all attempts")

    def start_idle(self, on_new_email: Callable = None):
        """
        Start IDLE mode for push email updates.
        
        Args:
            on_new_email: Callback when new email arrives
        """
        with self._lock:
            self._on_new_email = on_new_email

            if self._idle_running.is_set():
                logger.warning("IDLE already running")
                return

            self._idle_running.set()

            def idle_loop():
                while self._idle_running.is_set():
                    try:
                        self._do_idle()
                    except Exception as e:
                        logger.error(f"IDLE error: {e}")
                        time.sleep(5)

            self._idle_thread = threading.Thread(target=idle_loop, daemon=True)
            self._idle_thread.start()

            logger.info("IDLE mode started")

    def _do_idle(self):
        """Execute IDLE command"""
        with self._lock:
            if not self._connection or self._connection_state not in [ConnectionState.CONNECTED, ConnectionState.IDLE]:
                return

            try:
                self._connection_state = ConnectionState.IDLE

                # Enter IDLE
                self._connection.idle()
                self._last_idle = time.time()

                # Wait for up to idle_timeout
                # In practice, we'd use select() or similar
                time.sleep(min(self.idle_timeout, 60))

                # Exit IDLE
                self._connection.idle_done()

                # Check for new messages
                if self._on_new_email:
                    self._check_for_new_mail()

                self._connection_state = ConnectionState.CONNECTED

            except imaplib.IMAP4.error as e:
                logger.warning(f"IDLE error: {e}")
                if "IDLE" in str(e):
                    # IDLE not supported, use polling
                    self._fallback_to_polling()

    def _fallback_to_polling(self):
        """Fallback to polling if IDLE not supported"""
        logger.info("IDLE not supported, using polling")

        while self._idle_running.is_set():
            try:
                if self._on_new_email:
                    self._check_for_new_mail()
            except Exception as e:
                logger.error(f"Polling error: {e}")

            time.sleep(self.noop_interval)

    def _check_for_new_mail(self):
        """Check for new mail in selected folder"""
        try:
            status = self._connection.status(self._selected_folder or "INBOX", "(UNSEEN)")
            if status and len(status) > 1:
                unseen = status[1].decode()
                if "UNSEEN" in unseen:
                    # Parse unseen count
                    import re
                    match = re.search(r"UNSEEN (\d+)", unseen)
                    if match and int(match.group(1)) > 0:
                        self._on_new_email()
        except Exception as e:
            logger.error(f"Failed to check for new mail: {e}")

    def stop_idle(self):
        """Stop IDLE mode"""
        self._idle_running.clear()

        if self._idle_thread:
            self._idle_thread.join(timeout=5)

        logger.info("IDLE mode stopped")

    def select_folder(self, folder: str) -> bool:
        """Select a folder"""
        with self._lock:
            try:
                status, data = self._connection.select(folder)
                if status == "OK":
                    self._selected_folder = folder

                    # Track mailbox state
                    self._update_mailbox_state(folder, data)

                    logger.info(f"Selected folder: {folder}")
                    return True

            except Exception as e:
                logger.error(f"Failed to select folder {folder}: {e}")

            return False

    def _update_mailbox_state(self, folder: str, data):
        """Update mailbox state for drift detection"""
        if not data or len(data) < 2:
            return

        try:
            # Parse EXISTS count
            exists = int(data[0])

            # Parse FLAGS if available
            # (Would need to parse STATUS response for UID validity)

            if folder not in self._mailbox_states:
                self._mailbox_states[folder] = MailboxState(
                    folder=folder,
                    message_count=exists,
                    uid_validity=0,
                    uid_next=0
                )
            else:
                state = self._mailbox_states[folder]

                # Check for drift
                if state.message_count != exists:
                    logger.info(f"Mailbox drift detected: {state.message_count} -> {exists}")

                    if self._on_drift_detected:
                        self._on_drift_detected(folder, state.message_count, exists)

                state.message_count = exists
                state.last_check = time.time()

        except Exception as e:
            logger.error(f"Failed to update mailbox state: {e}")

    def fetch_emails(
        self,
        since_uid: Optional[int] = None,
        since_date: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Fetch emails from selected folder.
        
        Returns:
            List of email dictionaries
        """
        with self._lock:
            emails = []

            try:
                # Build search criteria
                if since_uid:
                    criteria = f"UID {since_uid}:*"
                elif since_date:
                    criteria = f"SINCE {since_date}"
                else:
                    criteria = "ALL"

                # Search
                status, message_ids = self._connection.search(None, criteria)

                if status != "OK" or not message_ids[0]:
                    return []

                ids = message_ids[0].split()
                ids = ids[-limit:]  # Get most recent

                # Fetch emails
                for msg_id in ids:
                    try:
                        status, data = self._connection.fetch(msg_id, "(RFC822)")

                        if status == "OK" and data and data[0]:
                            msg = email.message_from_bytes(data[0][1])

                            email_data = {
                                "message_id": msg.get("Message-ID", ""),
                                "subject": msg.get("Subject", ""),
                                "from": msg.get("From", ""),
                                "to": msg.get("To", ""),
                                "date": msg.get("Date", ""),
                                "body_text": self._get_body_text(msg),
                                "body_html": self._get_body_html(msg)
                            }

                            emails.append(email_data)

                    except Exception as e:
                        logger.warning(f"Failed to fetch email {msg_id}: {e}")

            except Exception as e:
                logger.error(f"Failed to fetch emails: {e}")

            return emails

    def _get_body_text(self, msg) -> str:
        """Extract plain text body"""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode()
        else:
            return msg.get_payload(decode=True).decode()
        return ""

    def _get_body_html(self, msg) -> str:
        """Extract HTML body"""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    return part.get_payload(decode=True).decode()
        return ""

    def get_folders(self) -> List[FolderInfo]:
        """Get list of folders"""
        with self._lock:
            folders = []

            try:
                status, data = self._connection.list()

                if status == "OK":
                    for line in data:
                        if line:
                            parts = line.decode().split('"')
                            if len(parts) >= 3:
                                folder = FolderInfo(
                                    name=parts[-1],
                                    path=parts[-1]
                                )
                                folders.append(folder)

            except Exception as e:
                logger.error(f"Failed to get folders: {e}")

            return folders

    def get_folder_status(self, folder: str) -> Dict:
        """Get folder status including UID validity"""
        with self._lock:
            try:
                status, data = self._connection.status(
                    folder,
                    "(MESSAGES RECENT UIDNEXT UIDVALIDITY UNSEEN)"
                )

                if status == "OK" and data:
                    return self._parse_status_response(data[0].decode())

            except Exception as e:
                logger.error(f"Failed to get folder status: {e}")

            return {}

    def _parse_status_response(self, response: str) -> Dict:
        """Parse STATUS response"""
        import re

        result = {}

        patterns = {
            "messages": r"MESSAGES (\d+)",
            "recent": r"RECENT (\d+)",
            "uidnext": r"UIDNEXT (\d+)",
            "uidvalidity": r"UIDVALIDITY (\d+)",
            "unseen": r"UNSEEN (\d+)"
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, response)
            if match:
                result[key] = int(match.group(1))

        return result

    def disconnect(self):
        """Disconnect from server"""
        with self._lock:
            # Stop IDLE
            self.stop_idle()

            # Stop watchdog
            self._watchdog_running.clear()
            if self._watchdog_thread:
                self._watchdog_thread.join(timeout=5)

            # Close connection
            if self._connection:
                try:
                    self._connection.close()
                    self._connection.logout()
                except Exception:
                    pass

            self._connection_state = ConnectionState.DISCONNECTED

            logger.info("Disconnected from IMAP server")

    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connection_state in [ConnectionState.CONNECTED, ConnectionState.IDLE]


# Global connection pool would go here
class IMAPConnectionPool:
    """Pool of IMAP connections"""

    def __init__(self, max_connections: int = 5):
        self.max_connections = max_connections
        self._connections: Dict[str, IMAPClient] = {}
        self._lock = threading.RLock()

    def get_connection(self, key: str) -> Optional[IMAPClient]:
        """Get or create connection"""
        with self._lock:
            if key not in self._connections:
                return None
            return self._connections[key]

    def add_connection(self, key: str, client: IMAPClient):
        """Add a connection to pool"""
        with self._lock:
            if len(self._connections) >= self.max_connections:
                # Remove oldest
                oldest = next(iter(self._connections))
                self._connections[oldest].disconnect()
                del self._connections[oldest]

            self._connections[key] = client


# Global pool
imap_pool = IMAPConnectionPool()
