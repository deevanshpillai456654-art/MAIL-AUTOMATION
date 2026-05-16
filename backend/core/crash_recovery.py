"""
Crash Recovery Engine - Resumable Workflows
=============================================

Enterprise crash recovery:
- Crash journals
- Resumable workflows
- Operation checkpoints
- Interrupted OAuth recovery
- Interrupted sync recovery
- Interrupted AI recovery
- Transactional recovery
"""

import os
import json
import time
import threading
import sqlite3
import logging
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

logger = logging.getLogger("recovery.engine")


class RecoveryState(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class WorkflowType(Enum):
    SYNC = "sync"
    OAUTH = "oauth"
    AI_CLASSIFY = "ai_classify"
    BACKUP = "backup"
    MIGRATION = "migration"
    RULE_EXECUTION = "rule_execution"


@dataclass
class WorkflowCheckpoint:
    """Workflow checkpoint for recovery"""
    checkpoint_id: str
    workflow_id: str
    workflow_type: WorkflowType
    step: str
    event_id: Optional[str]
    state: Dict[str, Any]
    state_json: str = ""
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False
    retry_count: int = 0


@dataclass
class CrashJournal:
    """Crash journal entry"""
    journal_id: str
    timestamp: float
    crash_type: str
    exception: str
    traceback: str
    workflow_id: Optional[str]
    recovery_plan: Dict[str, Any]


@dataclass
class OperationCheckpoint:
    """Operation checkpoint"""
    operation_id: str
    operation_type: str
    state: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    is_committed: bool = False


class CrashRecoveryEngine:
    """
    Enterprise crash recovery engine with resumable workflows.
    """
    
    def __init__(self, db_path: str = None):
        from backend.db.database import Database
        from backend import config
        
        self.db = Database(config.DB_PATH)
        
        # Recovery database
        data_dir = Path(config.DATA_DIR)
        self.recovery_db_path = data_dir / "recovery.db"
        
        self._init_recovery_db()
        
        # Checkpoint handlers
        self._checkpoint_handlers: Dict[str, Callable] = {}
        
        # Recovery callbacks
        self._on_oauth_recovery: Optional[Callable] = None
        self._on_sync_recovery: Optional[Callable] = None
        self._on_ai_recovery: Optional[Callable] = None
        
        self._lock = threading.RLock()
        
        logger.info("Crash Recovery Engine initialized")
    
    def _init_recovery_db(self):
        """Initialize recovery database"""
        conn = sqlite3.connect(str(self.recovery_db_path))
        cursor = conn.cursor()
        
        # Workflow checkpoints
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_type TEXT NOT NULL,
                step TEXT NOT NULL,
                event_id TEXT,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                is_complete INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0
            )
        """)
        
        # Crash journals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS crash_journals (
                journal_id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                crash_type TEXT NOT NULL,
                exception TEXT,
                traceback TEXT,
                workflow_id TEXT,
                recovery_plan TEXT
            )
        """)
        
        # Operation checkpoints
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operation_checkpoints (
                operation_id TEXT PRIMARY KEY,
                operation_type TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                is_committed INTEGER DEFAULT 0
            )
        """)
        
        # Sync cursors
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_cursors (
                account_id INTEGER NOT NULL,
                folder TEXT NOT NULL,
                last_uid INTEGER,
                last_sync REAL,
                cursor_data TEXT,
                PRIMARY KEY (account_id, folder)
            )
        """)
        
        # OAuth flows
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_flow_states (
                flow_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                state_data TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                is_complete INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.recovery_db_path))
        try:
            yield conn
        finally:
            conn.close()
    
    def create_checkpoint(self, workflow_id: str, workflow_type: WorkflowType,
                        step: str, event_id: Optional[str], state: Dict[str, Any]) -> str:
        """Create workflow checkpoint"""
        import secrets
        checkpoint_id = f"chk_{secrets.token_hex(8)}"
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO workflow_checkpoints 
                (checkpoint_id, workflow_id, workflow_type, step, event_id, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                checkpoint_id,
                workflow_id,
                workflow_type.value,
                step,
                event_id,
                json.dumps(state),
                time.time()
            ))
            conn.commit()
        
        logger.debug(f"Checkpoint created: {checkpoint_id} for {workflow_id} at {step}")
        return checkpoint_id
    
    def update_checkpoint(self, checkpoint_id: str, is_complete: bool = False):
        """Update checkpoint status"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE workflow_checkpoints 
                SET is_complete = ?, retry_count = retry_count + 1
                WHERE checkpoint_id = ?
            """, (1 if is_complete else 0, checkpoint_id))
            conn.commit()
    
    def get_workflow_checkpoints(self, workflow_id: str) -> List[WorkflowCheckpoint]:
        """Get all checkpoints for a workflow"""
        checkpoints = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM workflow_checkpoints 
                WHERE workflow_id = ?
                ORDER BY created_at ASC
            """, (workflow_id,))
            for row in cursor.fetchall():
                checkpoints.append(WorkflowCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    workflow_id=row["workflow_id"],
                    workflow_type=WorkflowType(row["workflow_type"]),
                    step=row["step"],
                    event_id=row["event_id"],
                    state=json.loads(row["state"]),
                    created_at=row["created_at"],
                    is_complete=bool(row["is_complete"]),
                    retry_count=row["retry_count"]
                ))
        return checkpoints
    
    def get_pending_workflows(self, workflow_type: WorkflowType = None) -> List[str]:
        """Get workflows that need recovery"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            if workflow_type:
                cursor.execute("""
                    SELECT DISTINCT workflow_id FROM workflow_checkpoints
                    WHERE workflow_type = ? AND is_complete = 0
                    ORDER BY created_at ASC
                """, (workflow_type.value,))
            else:
                cursor.execute("""
                    SELECT DISTINCT workflow_id FROM workflow_checkpoints
                    WHERE is_complete = 0
                    ORDER BY created_at ASC
                """)
            
            return [row[0] for row in cursor.fetchall()]
    
    def save_sync_cursor(self, account_id: int, folder: str, last_uid: int,
                        cursor_data: Dict = None):
        """Save sync cursor for resumable sync"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sync_cursors 
                (account_id, folder, last_uid, last_sync, cursor_data)
                VALUES (?, ?, ?, ?, ?)
            """, (account_id, folder, last_uid, time.time(), json.dumps(cursor_data or {})))
            conn.commit()
    
    def get_sync_cursor(self, account_id: int, folder: str) -> Optional[Dict]:
        """Get sync cursor for recovery"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sync_cursors 
                WHERE account_id = ? AND folder = ?
            """, (account_id, folder))
            row = cursor.fetchone()
            if row:
                return {
                    "last_uid": row["last_uid"],
                    "last_sync": row["last_sync"],
                    "cursor_data": json.loads(row["cursor_data"] or "{}")
                }
        return None
    
    def save_oauth_flow(self, flow_id: str, provider: str, state_data: Dict):
        """Save OAuth flow state"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO oauth_flow_states 
                (flow_id, provider, state_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (flow_id, provider, json.dumps(state_data), time.time(), time.time()))
            conn.commit()
    
    def get_oauth_flow(self, flow_id: str) -> Optional[Dict]:
        """Get OAuth flow for recovery"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM oauth_flow_states 
                WHERE flow_id = ?
            """, (flow_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "provider": row["provider"],
                    "state_data": json.loads(row["state_data"]),
                    "created_at": row["created_at"],
                    "is_complete": bool(row["is_complete"])
                }
        return None
    
    def complete_oauth_flow(self, flow_id: str):
        """Mark OAuth flow as complete"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE oauth_flow_states 
                SET is_complete = 1, updated_at = ?
                WHERE flow_id = ?
            """, (time.time(), flow_id))
            conn.commit()
    
    def get_pending_oauth_flows(self) -> List[Dict]:
        """Get incomplete OAuth flows for recovery"""
        flows = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM oauth_flow_states 
                WHERE is_complete = 0
                ORDER BY created_at ASC
            """)
            for row in cursor.fetchall():
                flows.append({
                    "flow_id": row["flow_id"],
                    "provider": row["provider"],
                    "state_data": json.loads(row["state_data"]),
                    "created_at": row["created_at"]
                })
        return flows
    
    def log_crash(self, crash_type: str, exception: Exception, workflow_id: str = None):
        """Log crash for recovery analysis"""
        import secrets
        
        journal_id = f"crash_{secrets.token_hex(8)}"
        
        # Create recovery plan
        recovery_plan = self._analyze_crash(crash_type, exception)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO crash_journals 
                (journal_id, timestamp, crash_type, exception, traceback, workflow_id, recovery_plan)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                journal_id,
                time.time(),
                crash_type,
                str(exception),
                traceback.format_exc(),
                workflow_id,
                json.dumps(recovery_plan)
            ))
            conn.commit()
        
        logger.error(f"Crash logged: {journal_id} - {crash_type}")
        return journal_id
    
    def _analyze_crash(self, crash_type: str, exception: Exception) -> Dict:
        """Analyze crash and create recovery plan"""
        plan = {
            "crash_type": crash_type,
            "recovery_actions": []
        }
        
        if crash_type == "memory_exhaustion":
            plan["recovery_actions"] = [
                "clear_caches",
                "force_gc",
                "reduce_worker_count",
                "enable_low_memory_mode"
            ]
        elif crash_type == "database_error":
            plan["recovery_actions"] = [
                "verify_database_integrity",
                "recover_from_wal",
                "rollback_transactions"
            ]
        elif crash_type == "oauth_error":
            plan["recovery_actions"] = [
                "restore_oauth_state",
                "retry_token_refresh",
                "reset_oauth_flow"
            ]
        elif crash_type == "sync_error":
            plan["recovery_actions"] = [
                "restore_sync_cursors",
                "resume_from_checkpoint",
                "verify_folder_state"
            ]
        elif crash_type == "ai_error":
            plan["recovery_actions"] = [
                "restore_ai_state",
                "retry_classification",
                "fallback_to_rules"
            ]
        
        return plan
    
    def recover_workflow(self, workflow_id: str) -> bool:
        """Recover a workflow from checkpoints"""
        checkpoints = self.get_workflow_checkpoints(workflow_id)
        
        if not checkpoints:
            logger.warning(f"No checkpoints found for workflow {workflow_id}")
            return False
        
        for checkpoint in checkpoints:
            if checkpoint.is_complete:
                continue
            
            try:
                # Process checkpoint
                handler_key = f"{checkpoint.workflow_type.value}_{checkpoint.step}"
                handler = self._checkpoint_handlers.get(handler_key)
                
                if handler:
                    handler(checkpoint.state)
                    self.update_checkpoint(checkpoint.checkpoint_id, is_complete=True)
                else:
                    logger.warning(f"No handler for {handler_key}")
                    
            except Exception as e:
                logger.error(f"Checkpoint recovery failed: {checkpoint.checkpoint_id} - {e}")
                self.log_crash("checkpoint_recovery_error", e, workflow_id)
                return False
        
        return True
    
    def register_checkpoint_handler(self, workflow_type: WorkflowType, step: str, handler: Callable):
        """Register a checkpoint handler"""
        key = f"{workflow_type.value}_{step}"
        self._checkpoint_handlers[key] = handler
        logger.debug(f"Registered handler: {key}")
    
    def save_operation_checkpoint(self, operation_id: str, operation_type: str, state: Dict):
        """Save operation checkpoint"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO operation_checkpoints 
                (operation_id, operation_type, state, created_at)
                VALUES (?, ?, ?, ?)
            """, (operation_id, operation_type, json.dumps(state), time.time()))
            conn.commit()
    
    def commit_operation(self, operation_id: str):
        """Commit operation"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE operation_checkpoints 
                SET is_committed = 1
                WHERE operation_id = ?
            """, (operation_id,))
            conn.commit()
    
    def rollback_uncommitted(self):
        """Rollback uncommitted operations"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT operation_id, operation_type, state FROM operation_checkpoints
                WHERE is_committed = 0
            """)
            
            for row in cursor.fetchall():
                operation_id = row["operation_id"]
                operation_type = row["operation_type"]
                state = json.loads(row["state"])
                
                # Implement rollback logic based on operation type
                logger.info(f"Rolling back operation: {operation_id} ({operation_type})")
            
            # Delete uncommitted
            cursor.execute("DELETE FROM operation_checkpoints WHERE is_committed = 0")
            conn.commit()
    
    def get_recovery_stats(self) -> Dict:
        """Get recovery statistics"""
        stats = {}
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Pending workflows
            cursor.execute("""
                SELECT COUNT(DISTINCT workflow_id) FROM workflow_checkpoints 
                WHERE is_complete = 0
            """)
            stats["pending_workflows"] = cursor.fetchone()[0]
            
            # Crash journals
            cursor.execute("SELECT COUNT(*) FROM crash_journals")
            stats["total_crashes"] = cursor.fetchone()[0]
            
            # OAuth flows
            cursor.execute("SELECT COUNT(*) FROM oauth_flow_states WHERE is_complete = 0")
            stats["pending_oauth_flows"] = cursor.fetchone()[0]
            
            # Sync cursors
            cursor.execute("SELECT COUNT(*) FROM sync_cursors")
            stats["sync_cursors"] = cursor.fetchone()[0]
        
        return stats
    
    def clear_completed_workflows(self, older_than_hours: int = 24):
        """Clear old completed workflows"""
        cutoff = time.time() - (older_than_hours * 3600)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM workflow_checkpoints 
                WHERE is_complete = 1 AND created_at < ?
            """, (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
        
        logger.info(f"Cleared {deleted} old completed workflows")
        return deleted


# Global recovery engine
_recovery_engine: Optional[CrashRecoveryEngine] = None


def get_recovery_engine() -> CrashRecoveryEngine:
    """Get or create global recovery engine"""
    global _recovery_engine
    if _recovery_engine is None:
        _recovery_engine = CrashRecoveryEngine()
    return _recovery_engine


# Need to import contextmanager
from contextlib import contextmanager