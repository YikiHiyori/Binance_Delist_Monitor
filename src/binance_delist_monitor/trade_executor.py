from __future__ import annotations

import time
from typing import Dict, List

from .config import AppConfig
from .trade_orchestrator import TradeOrchestrator


class TradeExecutor:
    def __init__(self, config: AppConfig):
        self.config = config
        self.orchestrator = TradeOrchestrator(config)
        self._last_monitor_run_at = 0.0

    def handle_signal(
        self,
        announcement_id: str,
        announcement_title: str,
        announcement_url: str,
        announcement_publish_time: str,
        matched_keywords: List[str],
        matched_symbols: List[str],
    ) -> Dict[str, object]:
        return self.orchestrator.handle_signal(
            announcement_id=announcement_id,
            announcement_title=announcement_title,
            announcement_url=announcement_url,
            announcement_publish_time=announcement_publish_time,
            matched_keywords=matched_keywords,
            matched_symbols=matched_symbols,
        )

    def monitor_positions_once(self):
        now = time.time()
        if now - self._last_monitor_run_at < float(self.config.price_poll_interval_seconds):
            return []
        self._last_monitor_run_at = now
        return self.orchestrator.monitor_positions_once()
