from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MonitorState:
    processed: Dict[str, str] = field(default_factory=dict)
    contract_cache: Dict[str, object] = field(default_factory=dict)
    pending_details: Dict[str, Dict[str, object]] = field(default_factory=dict)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.state = MonitorState()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.state = MonitorState()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.state = MonitorState()
            return
        self.state = MonitorState(
            processed=dict(payload.get("processed", {})),
            contract_cache=dict(payload.get("contract_cache", {})),
            pending_details=dict(payload.get("pending_details", {})),
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "processed": self.state.processed,
            "contract_cache": self.state.contract_cache,
            "pending_details": self.state.pending_details,
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        last_exc = None
        for _ in range(3):
            try:
                os.replace(str(tmp), str(self.path))
                return
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.2)
            except Exception as exc:
                last_exc = exc
                break
        try:
            self.path.write_text(data, encoding="utf-8")
            return
        except Exception as exc:
            last_exc = exc
        raise last_exc

    def is_processed(self, key: str) -> bool:
        return key in self.state.processed

    def mark_processed(self, key: str, value: Optional[str] = None) -> None:
        self.state.processed[key] = value or datetime.utcnow().isoformat()
        self.state.pending_details.pop(key, None)

    def is_detail_retry_due(self, key: str, now: Optional[datetime] = None) -> bool:
        pending = self.state.pending_details.get(key)
        if not pending:
            return True
        due_at = pending.get("next_retry_at")
        if not due_at:
            return True
        try:
            next_retry_at = datetime.fromisoformat(str(due_at))
        except Exception:
            return True
        return next_retry_at <= (now or datetime.utcnow())

    def mark_detail_retry(
        self,
        key: str,
        *,
        base_delay_seconds: int = 30,
        max_delay_seconds: int = 300,
        now: Optional[datetime] = None,
    ) -> Dict[str, object]:
        current_time = now or datetime.utcnow()
        existing = self.state.pending_details.get(key) or {}
        retry_count = int(existing.get("retry_count", 0)) + 1
        base_delay = max(1, int(base_delay_seconds))
        max_delay = max(base_delay, int(max_delay_seconds))
        delay_seconds = min(base_delay * (2 ** (retry_count - 1)), max_delay)
        pending = {
            "retry_count": retry_count,
            "last_attempt_at": current_time.isoformat(),
            "next_retry_at": (current_time + timedelta(seconds=delay_seconds)).isoformat(),
        }
        self.state.pending_details[key] = pending
        return pending

    def clear_detail_retry(self, key: str) -> None:
        self.state.pending_details.pop(key, None)

    def get_contract_cache(self):
        return self.state.contract_cache or {}

    def set_contract_cache(self, symbols: List[str], fetched_at: Optional[str] = None) -> None:
        self.state.contract_cache = {
            "symbols": symbols,
            "fetched_at": fetched_at or datetime.utcnow().isoformat(),
        }
