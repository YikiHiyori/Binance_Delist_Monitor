from __future__ import annotations

from datetime import datetime

from .capital_allocator import CapitalAllocator
from .position_store import PositionStore
from .structured_logger import StructuredLogger


class SignalLifecycleManager:
    def __init__(self, store: PositionStore, allocator: CapitalAllocator, logger: StructuredLogger):
        self.store = store
        self.allocator = allocator
        self.logger = logger

    def register_signal(self, signal_id: str, announcement_title: str, pool_id: str, pool_capital: float, total_positions: int) -> None:
        self.store.upsert_lifecycle(
            announcement_id=signal_id,
            announcement_title=announcement_title,
            pool_id=pool_id,
            total_positions=total_positions,
            open_positions=total_positions,
            completed=False,
            released_capital=pool_capital,
            total_realized_pnl=0.0,
        )

    def mark_position_closed(self, signal_id: str, close_pnl: float = 0.0) -> None:
        lifecycle = self.store.get_lifecycle(signal_id)
        if not lifecycle:
            return
        remaining = max(0, int(lifecycle["open_positions"]) - 1)
        realized = float(lifecycle["total_realized_pnl"]) + float(close_pnl)
        completed = remaining == 0
        self.store.update_lifecycle(
            signal_id,
            open_positions=remaining,
            completed=1 if completed else 0,
            total_realized_pnl=realized,
            updated_at=datetime.utcnow().isoformat(),
        )
        if completed:
            self.allocator.release_pool(lifecycle["pool_id"])
            self.logger.emit(
                "signal_completed",
                completion_time=datetime.utcnow().isoformat(),
                announcement_title=lifecycle["announcement_title"],
                pool_id=lifecycle["pool_id"],
                released_capital=lifecycle["released_capital"],
                total_positions=lifecycle["total_positions"],
                total_realized_pnl=realized,
                signal_status="completed",
            )
