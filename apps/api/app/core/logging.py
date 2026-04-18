import logging
import json
import sys
import time
from typing import Any, Dict

class JsonFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as JSON.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "filename": record.filename,
            "lineno": record.lineno,
        }
        
        # Add extra fields if they exist
        if hasattr(record, "extra_fields"):
            log_record.update(record.extra_fields)
            
        # Add exception info if it exists
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_record)

def setup_logging(level: str = "INFO"):
    """
    Configure structured JSON logging for the application.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    
    # Remove default handlers from other loggers to avoid duplicate logs
    for name in logging.root.manager.loggerDict:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

def log_request(logger: logging.Logger, method: str, path: str, status_code: int, duration_ms: float, extra: Dict[str, Any] = None):
    """
    Log an HTTP request with structured data.
    """
    fields = {
        "http_method": method,
        "http_path": path,
        "http_status": status_code,
        "duration_ms": duration_ms,
    }
    if extra:
        fields.update(extra)
        
    logger.info(f"{method} {path} {status_code} ({duration_ms:.2f}ms)", extra={"extra_fields": fields})
