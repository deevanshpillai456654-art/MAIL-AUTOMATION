"""
Data Export Manager
===================

Data export functionality:
- Export formats
- Export scheduling
- Export compression
- Export encryption
- Large export handling
"""

import os
import json
import csv
import zipfile
import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Iterator
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from backend import config

logger = logging.getLogger("data.export")


class ExportFormat(Enum):
    JSON = "json"
    CSV = "csv"
    XML = "xml"
    SQL = "sql"
    ZIP = "zip"


class ExportStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExportJob:
    """Export job"""
    job_id: str
    export_type: str
    format: ExportFormat
    status: ExportStatus = ExportStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    row_count: int = 0
    file_path: Optional[str] = None
    error: Optional[str] = None


class DataExporter:
    """
    Data export manager.
    """
    
    def __init__(self, export_dir: str = None):
        self.export_dir = Path(export_dir or config.DATA_DIR) / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        
        logger.info(f"DataExporter initialized: {self.export_dir}")
    
    def export_emails(
        self,
        format: ExportFormat = ExportFormat.JSON,
        limit: int = 10000,
        filters: Dict = None
    ) -> str:
        """Export emails"""
        import secrets
        job_id = f"export_{secrets.token_hex(8)}"
        
        # Start export in background
        threading.Thread(
            target=self._export_emails_async,
            args=(job_id, format, limit, filters),
            daemon=True
        ).start()
        
        return job_id
    
    def _export_emails_async(self, job_id: str, format: ExportFormat, limit: int, filters: Dict):
        """Async export"""
        try:
            # Get emails from DB
            conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM emails"
            params = []
            
            if filters:
                query += " WHERE 1=1"
                if filters.get("category"):
                    query += " AND category = ?"
                    params.append(filters["category"])
                if filters.get("account_id"):
                    query += " AND account_id = ?"
                    params.append(filters["account_id"])
            
            query += f" LIMIT {limit}"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            # Export based on format
            output_file = self.export_dir / f"{job_id}.{format.value}"
            
            if format == ExportFormat.JSON:
                self._export_json(rows, output_file)
            elif format == ExportFormat.CSV:
                self._export_csv(rows, output_file)
            
            logger.info(f"Export completed: {job_id} ({len(rows)} rows)")
        
        except Exception as e:
            logger.error(f"Export error: {e}")
    
    def _export_json(self, rows: List, file_path: Path):
        """Export as JSON"""
        data = [dict(row) for row in rows]
        
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _export_csv(self, rows: List, file_path: Path):
        """Export as CSV"""
        if not rows:
            return
        
        with open(file_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            
            for row in rows:
                writer.writerow(dict(row))
    
    def export_rules(
        self,
        format: ExportFormat = ExportFormat.JSON
    ) -> str:
        """Export rules"""
        import secrets
        job_id = f"export_rules_{secrets.token_hex(8)}"
        
        conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM rules LIMIT 10000")

        output_file = self.export_dir / f"{job_id}.{format.value}"

        if format == ExportFormat.JSON:
            rows = cursor.fetchall()
            self._export_json(rows, output_file)
        
        conn.close()
        
        return job_id
    
    def get_export_status(self, job_id: str) -> Optional[ExportJob]:
        """Get export status"""
        # Simple file-based status tracking
        output_file = self.export_dir / f"{job_id}.*"
        
        for f in self.export_dir.glob(f"{job_id}.*"):
            return ExportJob(
                job_id=job_id,
                export_type="emails",
                format=ExportFormat.JSON,
                status=ExportStatus.COMPLETED,
                file_path=str(f)
            )
        
        return None
    
    def cleanup_old_exports(self, days: int = 7):
        """Clean up old exports"""
        cutoff = time.time() - (days * 86400)
        
        for f in self.export_dir.glob("*"):
            if f.stat().st_mtime < cutoff:
                f.unlink()


# Global exporter
_data_exporter: Optional[DataExporter] = None


def get_data_exporter() -> DataExporter:
    """Get global exporter"""
    global _data_exporter
    if _data_exporter is None:
        _data_exporter = DataExporter()
    return _data_exporter


__all__ = ["DataExporter", "ExportJob", "ExportFormat", "ExportStatus", "get_data_exporter"]