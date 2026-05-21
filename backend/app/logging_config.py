import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


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
        file_handler = RotatingFileHandler(
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
