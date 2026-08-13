from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List

from .exchange_client import ExchangeClient
from .position_store import PositionStore
from .trade_models import OrderPlan, PositionRecord


class ExecutionBatchError(RuntimeError):
    def __init__(self, message: str, opened_records: List[PositionRecord]):
        super().__init__(message)
        self.opened_records = opened_records


class ExecutionEngine:
    def __init__(self, exchange: ExchangeClient, store: PositionStore, dry_run: bool, live_trading_enabled: bool, exchange_mode: str):
        self.exchange = exchange
        self.store = store
        self.dry_run = dry_run
        self.live_trading_enabled = live_trading_enabled
        self.exchange_mode = exchange_mode

    def _position_id(self, plan: OrderPlan) -> str:
        raw = f"{plan.signal_id}:{plan.pool_id}:{plan.symbol}:{plan.price}:{plan.quantity}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def execute(self, plans: List[OrderPlan]) -> List[PositionRecord]:
        records: List[PositionRecord] = []
        for plan in plans:
            try:
                if self.dry_run or self.exchange_mode in {"mock", "paper"}:
                    result = self.exchange.place_short_order(
                        plan.symbol,
                        plan.quantity,
                        plan.price,
                        dry_run=True,
                        leverage=plan.leverage,
                        margin_type=plan.margin_mode,
                    )
                else:
                    if not self.live_trading_enabled:
                        raise PermissionError("live trading requires DRY_RUN=false and LIVE_TRADING_ENABLED=true")
                    result = self.exchange.place_short_order(
                        plan.symbol,
                        plan.quantity,
                        plan.price,
                        leverage=plan.leverage,
                        margin_type=plan.margin_mode,
                    )
                position_id = self._position_id(plan)
                now = datetime.utcnow().isoformat()
                actual_allocated_capital = (float(result.price) * float(result.quantity)) / float(plan.leverage) if plan.leverage else float(result.price) * float(result.quantity)
                record = PositionRecord(
                    position_id=position_id,
                    trade_id=result.order_id,
                    signal_id=plan.signal_id,
                    announcement_id=plan.announcement_id,
                    announcement_title=plan.announcement_title,
                    announcement_url=plan.announcement_url,
                    symbol=plan.symbol,
                    side=plan.side,
                    pool_id=plan.pool_id,
                    allocated_capital=actual_allocated_capital,
                    leverage=plan.leverage,
                    entry_price=result.price,
                    quantity=result.quantity,
                    status="OPEN",
                    open_time=now,
                    exchange_delivery_time_ms=plan.exchange_delivery_time_ms,
                )
                self.store.insert_position(record)
                records.append(record)
            except Exception as exc:
                raise ExecutionBatchError(str(exc), records) from exc
        return records

    def close_position(
        self,
        position: dict,
        price: float | None,
        close_reason: str,
        execute_on_exchange: bool = True,
        realized_pnl: float | None = None,
        close_time: str | None = None,
    ) -> PositionRecord:
        if execute_on_exchange:
            if price is None:
                raise ValueError("price is required when submitting a close order")
            self.exchange.close_position(position["symbol"], position["quantity"], price, dry_run=self.dry_run)
        entry_price = float(position["entry_price"])
        qty = float(position["quantity"])
        pnl = float(realized_pnl) if realized_pnl is not None else (entry_price - float(price)) * qty
        pnl_pct = 0.0 if float(position["allocated_capital"]) == 0 else pnl / float(position["allocated_capital"])
        close_time = close_time or datetime.utcnow().isoformat()
        self.store.update_position(
            position["position_id"],
            status="CLOSED",
            close_time=close_time,
            close_price=float(price) if price is not None else None,
            close_reason=close_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )
        closed = dict(position)
        closed.update(
            {
                "status": "CLOSED",
                "close_time": close_time,
                "close_price": float(price) if price is not None else None,
                "close_reason": close_reason,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
        return PositionRecord(**closed)
