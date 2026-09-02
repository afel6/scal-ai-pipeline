import contextvars
import logging
import logging.handlers
import json
import os
from datetime import datetime, timezone

request_id_var = contextvars.ContextVar("request_id", default="-")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "module": record.name
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

def default_log_dir() -> str:
    """LOG_DIR if set, else <repo>/logs — never the CWD (D1)."""
    return os.getenv("LOG_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def setup_logging(debug_mode: bool):
    root_logger = logging.getLogger()
    # Clear existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    
    formatter = JSONFormatter() if not debug_mode else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    level = logging.DEBUG if debug_mode else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Rotating file handler (skip if the log dir can't be created — stdout logging still works)
    log_dir = default_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("File logging disabled, using stdout only: %s", exc)
