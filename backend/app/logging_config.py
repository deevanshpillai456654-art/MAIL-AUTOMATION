import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that survives Windows file-locking on rollover.

    Standard `RotatingFileHandler.doRollover()` uses `os.rename`, which fails
    on Windows with PermissionError (WinError 32) when another process or
    pytest plugin holds an open handle on the log file. When that happens we
    truncate the live file instead of rolling — losing the rotated archive
    but keeping the application running and the log file bounded.
    """

    def doRollover(self) -> None:  # type: ignore[override]
        try:
            super().doRollover()
        except PermissionError:
            # Another process holds the file open — truncate in place.
            try:
                if self.stream:
                    self.stream.close()
                    self.stream = None  # type: ignore[assignment]
                # Open for truncation, then re-open for append via the parent's
                # `_open` so future writes work normally.
                with open(self.baseFilename, "w", encoding=self.encoding or "utf-8"):
                    pass
                if not self.delay:
                    self.stream = self._open()
            except OSError:
                # Last-resort: silently swallow so logging never crashes the app.
                pass


def configure_logging(
    log_dir: str | Path,
    log_level: str,
    root_logger: logging.Logger | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    from backend.utils.logger import RedactingFormatter

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level, logging.INFO)
    formatter = RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = root_logger or logging.getLogger()
    logger.setLevel(level)

    log_file = log_path / "service.log"
    existing_file_handler = None
    for handler in logger.handlers:
        if (
            isinstance(handler, logging.FileHandler)
            and Path(getattr(handler, "baseFilename", "")) == log_file
        ):
            existing_file_handler = handler
            break

    if existing_file_handler:
        if isinstance(existing_file_handler, RotatingFileHandler):
            existing_file_handler.setFormatter(formatter)
            existing_file_handler.setLevel(level)
        else:
            logger.removeHandler(existing_file_handler)
            existing_file_handler.close()
            existing_file_handler = None
    if not existing_file_handler:
        # On Windows, file rotation can race with other handles on the same
        # file; use the safe subclass to keep logging alive across rollovers.
        handler_cls = WindowsSafeRotatingFileHandler if sys.platform == "win32" else RotatingFileHandler
        file_handler = handler_cls(
            log_file,
            maxBytes=max(1024, int(max_bytes)),
            backupCount=max(1, int(backup_count)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    stream_handler = next(
        (handler for handler in logger.handlers if type(handler) is logging.StreamHandler),
        None,
    )
    if stream_handler:
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
    else:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        logger.addHandler(stream_handler)

    return log_file


__all__ = ["configure_logging"]
