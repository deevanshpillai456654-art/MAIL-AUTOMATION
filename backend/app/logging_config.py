import logging
from pathlib import Path


def configure_logging(
    log_dir: str | Path,
    log_level: str,
    root_logger: logging.Logger | None = None,
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
        existing_file_handler.setFormatter(formatter)
        existing_file_handler.setLevel(level)
    else:
        file_handler = logging.FileHandler(log_file)
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
