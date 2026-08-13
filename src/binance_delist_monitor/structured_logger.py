from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict


class StructuredLogger:
    def __init__(self, name: str, log_file: Path):
        log_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        for handler in list(self.logger.handlers):
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            self.logger.removeHandler(handler)
        self.logger.propagate = False

        formatter = logging.Formatter("%(message)s")
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(stream)
        self.logger.addHandler(file_handler)
        self._handlers = [stream, file_handler]

    def emit(self, event_type: str, **fields: Any) -> None:
        payload: Dict[str, Any] = {"event_type": event_type, **fields}
        self.logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

    def info(self, message: str, **fields: Any) -> None:
        self.emit("info", message=message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self.emit("warning", message=message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self.emit("error", message=message, **fields)

    def close(self) -> None:
        for handler in self._handlers:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            try:
                self.logger.removeHandler(handler)
            except Exception:
                pass
