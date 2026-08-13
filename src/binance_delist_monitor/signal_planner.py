from __future__ import annotations

import hashlib
from typing import List

from .exchange_client import ExchangeClient
from .trade_models import OrderPlan, SignalContext


def _signal_id(announcement_id: str, symbols: List[str]) -> str:
    raw = f"{announcement_id}:{','.join(symbols)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class SignalToOrderPlanner:
    def __init__(self, leverage: int = 1):
        self.leverage = int(leverage)

    def build_signal(
        self,
        announcement_id: str,
        announcement_title: str,
        announcement_url: str,
        announcement_publish_time: str,
        matched_keywords: List[str],
        matched_symbols: List[str],
        pool_id: str,
        pool_capital: float,
        strategy_total_capital: float,
        available_balance: float,
        capital_basis: str,
        pool_rebalanced: bool,
    ) -> SignalContext:
        return SignalContext(
            signal_id=_signal_id(announcement_id, matched_symbols),
            announcement_id=announcement_id,
            announcement_title=announcement_title,
            announcement_url=announcement_url,
            announcement_publish_time=announcement_publish_time,
            matched_keywords=matched_keywords,
            matched_symbols=matched_symbols,
            triggered_at=__import__("datetime").datetime.utcnow().isoformat(),
            pool_id=pool_id,
            pool_capital=float(pool_capital),
            symbol_count=len(matched_symbols),
            strategy_total_capital=float(strategy_total_capital),
            available_balance=float(available_balance),
            capital_basis=capital_basis,
            pool_rebalanced=bool(pool_rebalanced),
            status="planned",
        )

    def plan_orders(self, signal: SignalContext, exchange: ExchangeClient) -> List[OrderPlan]:
        if not signal.pool_id or not signal.matched_symbols:
            return []
        average_allocation = float(signal.pool_capital) / float(len(signal.matched_symbols))
        symbol_cap = float(signal.strategy_total_capital) * 0.2
        plans: List[OrderPlan] = []
        for index, symbol in enumerate(signal.matched_symbols):
            price = float(exchange.get_price(symbol))
            delivery_time_ms = exchange.get_symbol_delivery_time(symbol, force_refresh=index == 0)
            requested_capital = min(average_allocation, symbol_cap)
            target_notional = requested_capital * self.leverage
            quantity = 0.0 if price <= 0 else target_notional / price
            quantity = float(exchange.round_quantity(symbol, quantity))
            if quantity <= 0:
                continue
            actual_notional = float(quantity) * float(price)
            plans.append(
                OrderPlan(
                    symbol=symbol,
                    side="SHORT",
                    requested_capital=requested_capital,
                    allocated_capital=actual_notional / float(self.leverage) if self.leverage else actual_notional,
                    average_allocation=average_allocation,
                    symbol_cap=symbol_cap,
                    cap_applied=requested_capital < average_allocation,
                    leverage=self.leverage,
                    price=price,
                    quantity=quantity,
                    notional=actual_notional,
                    margin_mode="CROSSED",
                    announcement_id=signal.announcement_id,
                    announcement_title=signal.announcement_title,
                    announcement_url=signal.announcement_url,
                    pool_id=signal.pool_id,
                    signal_id=signal.signal_id,
                    exchange_delivery_time_ms=delivery_time_ms,
                )
            )
        return plans
