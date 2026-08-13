from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .position_store import PositionStore
from .trade_models import Pool


@dataclass
class AllocationDecision:
    pool_id: Optional[str]
    pool_capital: float
    status: str
    reason: Optional[str] = None


class CapitalAllocator:
    def __init__(self, total_capital: float, max_active_signal_pools: int, allow_signal_queue: bool, store: PositionStore):
        self.total_capital = float(total_capital)
        self.max_active_signal_pools = int(max_active_signal_pools)
        self.allow_signal_queue = bool(allow_signal_queue)
        self.store = store
        self._ensure_pools()

    @staticmethod
    def _split_capital(total_capital: float) -> Dict[str, float]:
        total = float(total_capital)
        return {"A": total * 0.6, "B": total * 0.4}

    def _ensure_pools(self) -> None:
        allocations = self._split_capital(self.total_capital)
        now = datetime.utcnow().isoformat()
        self.store.seed_pools(
            [
                Pool(pool_id="A", status="idle", allocated_capital=allocations["A"], created_at=now, updated_at=now),
                Pool(pool_id="B", status="idle", allocated_capital=allocations["B"], created_at=now, updated_at=now),
            ]
        )
        self._recover_pool_states(allocations)

    def _recover_pool_states(self, default_allocations: Dict[str, float]) -> None:
        now = datetime.utcnow().isoformat()
        for pool in self.store.get_pools():
            pool_id = str(pool["pool_id"])
            open_positions = self.store.list_open_positions_by_pool(pool_id)
            occupied = bool(open_positions)
            signal_id = open_positions[0]["signal_id"] if open_positions else None
            updates: Dict[str, object] = {}
            target_status = "occupied" if occupied else "idle"
            if pool.get("status") != target_status:
                updates["status"] = target_status
            if pool.get("announcement_key") != signal_id:
                updates["announcement_key"] = signal_id
            if float(pool.get("allocated_capital") or 0.0) <= 0:
                updates["allocated_capital"] = float(default_allocations.get(pool_id, 0.0))
            if updates:
                updates["updated_at"] = now
                self.store.update_pool(pool_id, **updates)

    def all_pools_idle(self) -> bool:
        pools = self.store.get_pools()
        if not pools:
            return True
        return all(str(pool.get("status", "")).lower() == "idle" for pool in pools)

    def rebase_pools(self, account_balance: float) -> Dict[str, float]:
        account_balance = float(account_balance)
        if account_balance <= 0:
            raise ValueError("account balance must be positive")
        if not self.all_pools_idle():
            raise RuntimeError("pool rebalance requires all pools to be idle")
        self.total_capital = account_balance
        allocations = self._split_capital(account_balance)
        now = datetime.utcnow().isoformat()
        for pool in self.store.get_pools():
            pool_id = str(pool["pool_id"])
            self.store.update_pool(
                pool_id,
                status="idle",
                announcement_key=None,
                allocated_capital=float(allocations.get(pool_id, 0.0)),
                updated_at=now,
            )
        return allocations

    def choose_pool(self, announcement_id: str) -> AllocationDecision:
        pools = self.store.get_pools()
        occupied = [p for p in pools if p["status"] == "occupied"]
        if len(occupied) >= self.max_active_signal_pools:
            return AllocationDecision(
                pool_id=None,
                pool_capital=0.0,
                status="queued" if self.allow_signal_queue else "skipped",
                reason="no_available_pool",
            )
        target = None
        for preferred in ("A", "B"):
            target = next((p for p in pools if p["pool_id"] == preferred and p["status"] == "idle"), None)
            if target is not None:
                break
        if target is None:
            return AllocationDecision(
                pool_id=None,
                pool_capital=0.0,
                status="queued" if self.allow_signal_queue else "skipped",
                reason="no_idle_pool",
            )
        self.store.update_pool(target["pool_id"], status="occupied", announcement_key=announcement_id, updated_at=datetime.utcnow().isoformat())
        return AllocationDecision(pool_id=target["pool_id"], pool_capital=float(target["allocated_capital"]), status="allocated")

    def release_pool(self, pool_id: str) -> None:
        self.store.update_pool(pool_id, status="idle", announcement_key=None, updated_at=datetime.utcnow().isoformat())

    def pool_summary(self) -> List[Dict[str, object]]:
        return self.store.get_pools()
