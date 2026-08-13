from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Pool:
    pool_id: str
    status: str = "idle"
    announcement_key: Optional[str] = None
    allocated_capital: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SignalContext:
    signal_id: str
    announcement_id: str
    announcement_title: str
    announcement_url: str
    announcement_publish_time: str
    matched_keywords: List[str]
    matched_symbols: List[str]
    triggered_at: str
    pool_id: Optional[str] = None
    pool_capital: float = 0.0
    symbol_count: int = 0
    strategy_total_capital: float = 0.0
    available_balance: float = 0.0
    capital_basis: str = "totalMarginBalance"
    pool_rebalanced: bool = False
    status: str = "new"
    notes: Dict[str, object] = field(default_factory=dict)


@dataclass
class OrderPlan:
    symbol: str
    side: str
    requested_capital: float
    allocated_capital: float
    average_allocation: float
    symbol_cap: float
    cap_applied: bool
    leverage: int
    price: float
    quantity: float
    notional: float
    margin_mode: str
    announcement_id: str
    announcement_title: str
    announcement_url: str
    pool_id: str
    signal_id: str
    exchange_delivery_time_ms: Optional[int] = None


@dataclass
class PositionRecord:
    position_id: str
    trade_id: str
    signal_id: str
    announcement_id: str
    announcement_title: str
    announcement_url: str
    symbol: str
    side: str
    pool_id: str
    allocated_capital: float
    leverage: int
    entry_price: float
    quantity: float
    status: str
    open_time: str
    exchange_delivery_time_ms: Optional[int] = None
    close_time: Optional[str] = None
    close_price: Optional[float] = None
    close_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class PositionSnapshot:
    position_id: str
    symbol: str
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    trigger_status: str
    check_time: str


@dataclass(frozen=True)
class AccountSnapshot:
    available_balance: float
    total_margin_balance: float
    total_wallet_balance: float
    total_unrealized_profit: float
    fetched_at: str
    capital_basis: str = "totalMarginBalance"

    @property
    def strategy_total_capital(self) -> float:
        return float(self.total_margin_balance)


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def iso_to_timestamp_ms(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def timestamp_ms_to_iso(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc).replace(tzinfo=None).isoformat()
