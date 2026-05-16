"""
Log Processor - Centralized Logging
=================================

Centralized log processing:
- Log aggregation
- Log filtering
- Log rotation
- Structured logging
- Log analysis
"""

import os
import re
import json
import time
import logging
import threading
from typing import Any, Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger("log.processor")


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """Log entry"""
    timestamp: float
    level: str
    logger: str
    message: str
    extra: Dict[str, Any] = field(default_factory=dict)


class LogProcessor:
    """
    Centralized log processor.
    """
    
    def __init__(self, max_entries: int = 10000):
        self.max_entries = max_entries
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        
        # Filters
        self._level_filter = LogLevel.INFO
        self._pattern_filter: Optional[re.Pattern] = None
        
        logger.info("LogProcessor initialized")
    
    def add_entry(
        self,
        level: str,
        logger_name: str,
        message: str,
        extra: Dict = None
    ):
        """Add log entry"""
        # Apply filters
        if self._pattern_filter and not self._pattern_filter.search(message):
            return
        
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            logger=logger_name,
            message=message,
            extra=extra or {}
        )
        
        with self._lock:
            self._entries.append(entry)
    
    def set_level_filter(self, level: LogLevel):
        """Set level filter"""
        self._level_filter = level
    
    def set_pattern_filter(self, pattern: str):
        """Set pattern filter"""
        self._pattern_filter = re.compile(pattern)
    
    def get_entries(
        self,
        level: str = None,
        logger_name: str = None,
        limit: int = 100
    ) -> List[LogEntry]:
        """Get filtered entries"""
        with self._lock:
            entries = list(self._entries)
        
        if level:
            entries = [e for e in entries if e.level == level]
        
        if logger_name:
            entries = [e for e in entries if e.logger == logger_name]
        
        return entries[-limit:]
    
    def get_stats(self) -> Dict:
        """Get log stats"""
        with self._lock:
            entries = list(self._entries)
        
        by_level = {}
        for e in entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
        
        return {
            "total": len(entries),
            "by_level": by_level
        }
    
    def export_json(self, path: str) -> bool:
        """Export logs to JSON"""
        try:
            with open(path, "w") as f:
                with self._lock:
                    for entry in self._entries:
                        f.write(json.dumps({
                            "timestamp": entry.timestamp,
                            "level": entry.level,
                            "logger": entry.logger,
                            "message": entry.message,
                            **entry.extra
                        }) + "\n")
            return True
        except Exception as e:
            logger.error(f"Export error: {e}")
            return False


class StructuredLogger:
    """
    Structured logger wrapper.
    """
    
    def __init__(self, name: str, processor: LogProcessor = None):
        self.name = name
        self.processor = processor or _log_processor
    
    def debug(self, message: str, **extra):
        self.processor.add_entry("DEBUG", self.name, message, extra)
    
    def info(self, message: str, **extra):
        self.processor.add_entry("INFO", self.name, message, extra)
    
    def warning(self, message: str, **extra):
        self.processor.add_entry("WARNING", self.name, message, extra)
    
    def error(self, message: str, **extra):
        self.processor.add_entry("ERROR", self.name, message, extra)
    
    def critical(self, message: str, **extra):
        self.processor.add_entry("CRITICAL", self.name, message, extra)


# Global log processor
_log_processor: Optional[LogProcessor] = None


def get_log_processor() -> LogProcessor:
    """Get global log processor"""
    global _log_processor
    if _log_processor is None:
        _log_processor = LogProcessor()
    return _log_processor


def get_structured_logger(name: str) -> StructuredLogger:
    """Get structured logger"""
    return StructuredLogger(name, get_log_processor())


__all__ = ["LogProcessor", "LogEntry", "StructuredLogger", "get_log_processor", "get_structured_logger"]