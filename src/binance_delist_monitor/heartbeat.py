from __future__ import annotations

from datetime import datetime


class Heartbeat:
    def __init__(self):
        self.last_heartbeat = None

    def due(self, interval_seconds: int) -> bool:
        if self.last_heartbeat is None:
            return True
        delta = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return delta >= interval_seconds

    def beat(self) -> None:
        self.last_heartbeat = datetime.utcnow()
