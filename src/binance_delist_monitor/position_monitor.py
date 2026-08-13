from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .exchange_client import ExchangeClient, ExchangePosition
from .execution_engine import ExecutionEngine
from .position_store import PositionStore
from .structured_logger import StructuredLogger
from .trade_models import iso_to_timestamp_ms, timestamp_ms_to_iso


class PositionMonitor:
    RECONCILE_INCOME_TYPES = {
        "REALIZED_PNL",
        "COMMISSION",
        "FUNDING_FEE",
        "INSURANCE_CLEAR",
        "DELIVERED_SETTELMENT",
        "DELIVERED_SETTLEMENT",
    }

    def __init__(
        self,
        exchange: ExchangeClient,
        store: PositionStore,
        engine: ExecutionEngine,
        logger: StructuredLogger,
        enable_take_profit: bool,
        take_profit_pct: float,
    ):
        self.exchange = exchange
        self.store = store
        self.engine = engine
        self.logger = logger
        self.enable_take_profit = enable_take_profit
        self.take_profit_pct = float(take_profit_pct)

    def _tp_triggered(self, entry_price: float, current_price: float) -> bool:
        return current_price <= entry_price * (1 - self.take_profit_pct)

    @staticmethod
    def _position_key(symbol: str, side: str) -> Tuple[str, str]:
        return symbol.upper(), side.upper()

    def _load_signal_notes(self, signal_id: str) -> Dict[str, object]:
        signal = self.store.get_signal(signal_id)
        if not signal:
            return {}
        notes = signal.get("notes")
        if isinstance(notes, dict):
            return notes
        if isinstance(notes, str) and notes:
            try:
                parsed = json.loads(notes)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _resolve_exchange_delivery_time_ms(self, position: Dict[str, object], signal_notes: Dict[str, object]) -> Optional[int]:
        direct_value = position.get("exchange_delivery_time_ms")
        if direct_value not in (None, ""):
            return int(direct_value)
        delivery_map = signal_notes.get("symbol_delivery_times")
        if isinstance(delivery_map, dict):
            symbol_value = delivery_map.get(str(position["symbol"]).upper())
            if symbol_value not in (None, ""):
                return int(symbol_value)
        return None

    @staticmethod
    def _sum_income(records: List[object]) -> float:
        return float(sum(float(record.income) for record in records))

    def evaluate_position(
        self,
        position: Dict[str, object],
        exchange_positions: Dict[Tuple[str, str], ExchangePosition],
    ) -> Dict[str, object]:
        symbol = str(position["symbol"]).upper()
        exchange_position = exchange_positions.get(self._position_key(symbol, "SHORT"))
        check_time = datetime.utcnow().isoformat()

        if exchange_position is None or exchange_position.quantity <= 0:
            signal_notes = self._load_signal_notes(str(position["signal_id"]))
            delivery_time_ms = self._resolve_exchange_delivery_time_ms(position, signal_notes)
            try:
                refreshed_delivery_time_ms = self.exchange.get_symbol_delivery_time(symbol, force_refresh=True)
            except Exception:
                refreshed_delivery_time_ms = None
            if refreshed_delivery_time_ms is not None:
                delivery_time_ms = int(refreshed_delivery_time_ms)
            check_time_ms = iso_to_timestamp_ms(check_time) or int(datetime.utcnow().timestamp() * 1000)
            symbol_active = self.exchange.is_symbol_tradable(symbol)
            delivery_due = delivery_time_ms is not None and check_time_ms >= int(delivery_time_ms)
            close_reason = "exchange_delist_closed" if delivery_due or not symbol_active else "sync_detected_closed"
            open_time_ms = iso_to_timestamp_ms(str(position["open_time"]))
            start_time_ms = max(0, int(open_time_ms) - 60000) if open_time_ms is not None else None
            income_records = []
            income_error = None
            try:
                income_records = self.exchange.get_income_history(
                    symbol,
                    start_time_ms=start_time_ms,
                    end_time_ms=check_time_ms,
                    income_types=self.RECONCILE_INCOME_TYPES,
                )
            except Exception as exc:
                income_error = str(exc)

            realized_pnl = None
            close_price = None
            close_time_override = check_time
            close_value_source = "income_history"
            income_types = sorted({record.income_type for record in income_records})
            if income_records:
                realized_pnl = self._sum_income(income_records)
                close_time_override = timestamp_ms_to_iso(max(record.time_ms for record in income_records)) or check_time
            elif close_reason == "sync_detected_closed":
                try:
                    close_price = float(self.exchange.get_price(symbol))
                    close_value_source = "market_price_fallback"
                except Exception as exc:
                    income_error = income_error or str(exc)
            else:
                self.logger.emit(
                    "position_sync",
                    check_time=check_time,
                    position_id=position["position_id"],
                    signal_id=position["signal_id"],
                    symbol=symbol,
                    exchange_position_found=False,
                    exchange_symbol_active=symbol_active,
                    exchange_delivery_time_ms=delivery_time_ms,
                    exchange_delivery_time=timestamp_ms_to_iso(delivery_time_ms),
                    delivery_due=delivery_due,
                    close_reason=close_reason,
                    income_record_count=0,
                    income_types=[],
                    reconcile_status="awaiting_income_history",
                    income_error=income_error,
                )
                return {
                    "closed": False,
                    "position_id": position["position_id"],
                    "trigger_status": "awaiting_income_history",
                    "close_reason": close_reason,
                }
            self.logger.emit(
                "position_sync",
                check_time=check_time,
                position_id=position["position_id"],
                signal_id=position["signal_id"],
                symbol=symbol,
                exchange_position_found=False,
                exchange_symbol_active=symbol_active,
                exchange_delivery_time_ms=delivery_time_ms,
                exchange_delivery_time=timestamp_ms_to_iso(delivery_time_ms),
                delivery_due=delivery_due,
                close_reason=close_reason,
                close_price_source=close_value_source,
                income_record_count=len(income_records),
                income_types=income_types,
                realized_pnl=realized_pnl,
                reconcile_status="closed",
                income_error=income_error,
            )
            closed = self.engine.close_position(
                position,
                close_price,
                close_reason,
                execute_on_exchange=False,
                realized_pnl=realized_pnl,
                close_time=close_time_override,
            )
            self.logger.emit(
                "position_closed",
                close_time=closed.close_time,
                position_id=closed.position_id,
                symbol=closed.symbol,
                close_price=closed.close_price,
                pnl=closed.pnl,
                pnl_pct=closed.pnl_pct,
                close_reason=close_reason,
                close_value_source=close_value_source,
                exchange_delivery_time_ms=delivery_time_ms,
                exchange_delivery_time=timestamp_ms_to_iso(delivery_time_ms),
                related_announcement_title=closed.announcement_title,
                related_pool_id=closed.pool_id,
            )
            return {
                "closed": True,
                "position_id": position["position_id"],
                "close_reason": close_reason,
                "close_price": closed.close_price,
                "pnl": closed.pnl,
            }

        current_price = float(exchange_position.mark_price or 0.0)
        if current_price <= 0:
            current_price = float(self.exchange.get_price(symbol))
        entry_price = float(position["entry_price"])
        allocated_capital = float(position["allocated_capital"])
        unrealized_pnl = float(exchange_position.unrealized_pnl)
        if exchange_position.mark_price <= 0:
            unrealized_pnl = (entry_price - current_price) * float(position["quantity"])
        unrealized_pnl_pct = 0.0 if allocated_capital == 0 else unrealized_pnl / allocated_capital
        trigger_status = "hold"
        close_reason = None

        if self.enable_take_profit and self._tp_triggered(entry_price, current_price):
            trigger_status = "tp_hit"
            close_reason = "tp_hit"

        self.logger.emit(
            "position_check",
            check_time=check_time,
            position_id=position["position_id"],
            signal_id=position["signal_id"],
            symbol=symbol,
            current_price=current_price,
            entry_price=entry_price,
            exchange_quantity=exchange_position.quantity,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            tp_threshold=self.take_profit_pct,
            tp_enabled=self.enable_take_profit,
            trigger_status=trigger_status,
        )

        if close_reason:
            self.logger.emit(
                "close_submit_request",
                submit_time=check_time,
                position_id=position["position_id"],
                symbol=symbol,
                quantity=float(position["quantity"]),
                side="BUY",
                order_type="MARKET",
                reduce_only=True,
                margin_mode="CROSSED",
                leverage=1,
                close_reason=close_reason,
            )
            closed = self.engine.close_position(position, current_price, close_reason, execute_on_exchange=True)
            self.logger.emit(
                "position_closed",
                close_time=closed.close_time,
                position_id=closed.position_id,
                symbol=closed.symbol,
                close_price=current_price,
                pnl=closed.pnl,
                pnl_pct=closed.pnl_pct,
                close_reason=close_reason,
                related_announcement_title=closed.announcement_title,
                related_pool_id=closed.pool_id,
            )
            return {
                "closed": True,
                "position_id": position["position_id"],
                "close_reason": close_reason,
                "close_price": current_price,
                "pnl": closed.pnl,
            }

        return {"closed": False, "position_id": position["position_id"], "trigger_status": trigger_status}

    def scan_open_positions(self) -> List[Dict[str, object]]:
        positions = self.store.list_open_positions()
        exchange_positions = {
            self._position_key(exchange_position.symbol, exchange_position.side): exchange_position
            for exchange_position in self.exchange.list_positions()
        }
        results: List[Dict[str, object]] = []
        for position in positions:
            results.append(self.evaluate_position(position, exchange_positions))
        return results
