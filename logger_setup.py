import contextvars
import logging
import json
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

def setup_logging(debug_mode: bool):
    root_logger = logging.getLogger()
    # Clear existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    
    handler = logging.StreamHandler()
    if not debug_mode:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)
