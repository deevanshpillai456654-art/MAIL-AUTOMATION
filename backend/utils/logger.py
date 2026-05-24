"""
Logging utilities for AI Email Organizer
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

try:
    from backend.security.redaction import redact_text as _redact_text
except ImportError:
    def _redact_text(v: str, **_) -> str:  # type: ignore[misc]
        return v


class RedactingFormatter(logging.Formatter):
    """Formatter that scrubs tokens, secrets and credentials from every log record."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = _redact_text(str(record.msg))
        if record.args:
            try:
                record.msg = record.msg % record.args
            except Exception:
                pass
            record.args = None
        return super().format(record)


def setup_logger(
    name: str,
    log_path: str = None,
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = RedactingFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        # On Windows, the standard RotatingFileHandler crashes on rollover if
        # another handle (test worker, previous run) is open on the file.
        try:
            from backend.app.logging_config import WindowsSafeRotatingFileHandler
            handler_cls = WindowsSafeRotatingFileHandler if sys.platform == "win32" else RotatingFileHandler
        except ImportError:
            handler_cls = RotatingFileHandler
        file_handler = handler_cls(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class LoggerMixin:
    @property
    def logger(self) -> logging.Logger:
        if not hasattr(self, "_logger"):
            self._logger = logging.getLogger(self.__class__.__name__)
        return self._logger
