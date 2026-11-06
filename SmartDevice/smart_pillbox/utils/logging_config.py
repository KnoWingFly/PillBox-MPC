import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from smart_pillbox import config


def configure_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    """Console plus a rotating file (default: the profile's pillbox.log), so a problem seen in a
    demo can still be read after the window is closed."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    path = log_file or config.log_path(config.PROFILE)
    file_error: OSError | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=config.LOG_FILE_MAX_BYTES,
                backupCount=config.LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    except OSError as exc:  # read-only folder: console logging still works
        file_error = exc
    logging.basicConfig(level=level, format=config.LOG_FORMAT, datefmt=config.LOG_DATE_FORMAT, handlers=handlers)
    if file_error is not None:
        logging.getLogger(__name__).warning("No log file at %s: %s", path, file_error)
