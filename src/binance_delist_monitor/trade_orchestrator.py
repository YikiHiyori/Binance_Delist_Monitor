from __future__ import annotations

from typing import Dict, List, Tuple

from .capital_allocator import CapitalAllocator
from .config import AppConfig
from .exchange_client import BinanceFuturesClient, ExchangeClient, MockExchangeClient
from .execution_engine import ExecutionBatchError, ExecutionEngine
from .position_monitor import PositionMonitor
from .position_store import PositionStore
from .signal_lifecycle import SignalLifecycleManager
from .signal_planner import SignalToOrderPlanner
from .structured_logger import StructuredLogger
from .trade_models import AccountSnapshot, OrderPlan, timestamp_ms_to_iso


class TradeOrchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = PositionStore(config.trading_db_file)
        self.logger = StructuredLogger("binance_delist_monitor.trades", config.log_file)
        self.exchange = self._build_exchange()
        self.allocator = CapitalAllocator(config.total_capital, config.max_active_signal_pools, config.allow_signal_queue, self.store)
        self.planner = SignalToOrderPlanner(leverage=1)
        self.engine = ExecutionEngine(self.exchange, self.store, config.dry_run, config.live_trading_enabled, config.exchange_mode)
        self.lifecycle = SignalLifecycleManager(self.store, self.allocator, self.logger)
        self.monitor = PositionMonitor(
            self.exchange,
            self.store,
            self.engine,
            self.logger,
            config.enable_take_profit,
            config.take_profit_pct,
        )

    def _build_exchange(self) -> ExchangeClient:
        if self.config.exchange_mode in {"mock", "paper"} or self.config.dry_run or not self.config.live_trading_enabled:
            return MockExchangeClient(default_price=100.0, account_balance=self.config.total_capital)
        return BinanceFuturesClient(
            self.config.binance_api_key,
            self.config.binance_api_secret,
            self.config.live_trading_enabled,
            self.config.dry_run,
            testnet=self.config.exchange_mode == "testnet",
        )

    def _load_account_snapshot(self) -> AccountSnapshot:
        return self.exchange.get_account_snapshot()

    def _current_pool_allocations(self) -> Dict[str, float]:
        return {str(pool["pool_id"]): float(pool["allocated_capital"]) for pool in self.allocator.pool_summary()}

    def _maybe_rebalance_pools(self, snapshot: AccountSnapshot) -> Tuple[bool, Dict[str, float]]:
        if self.allocator.all_pools_idle():
            allocations = self.allocator.rebase_pools(snapshot.strategy_total_capital)
            return True, allocations
        return False, self._current_pool_allocations()

    def _emit_capital_snapshot(
        self,
        *,
        snapshot: AccountSnapshot,
        pool_allocations: Dict[str, float],
        announcement_title: str,
        announcement_publish_time: str,
        matched_symbols: List[str],
        pool_rebalanced: bool,
        selected_pool_id: str | None,
    ) -> None:
        self.logger.emit(
            "capital_snapshot",
            trigger_time=announcement_publish_time,
            announcement_title=announcement_title,
            matched_symbols=matched_symbols,
            selected_pool_id=selected_pool_id,
            capital_basis=snapshot.capital_basis,
            strategy_total_capital=snapshot.strategy_total_capital,
            available_balance=snapshot.available_balance,
            total_margin_balance=snapshot.total_margin_balance,
            total_wallet_balance=snapshot.total_wallet_balance,
            total_unrealized_profit=snapshot.total_unrealized_profit,
            pool_rebalanced=pool_rebalanced,
            pool_a_capital=float(pool_allocations.get("A", 0.0)),
            pool_b_capital=float(pool_allocations.get("B", 0.0)),
            account_snapshot_time=snapshot.fetched_at,
        )

    def _emit_order_plans(self, signal_id: str, orders: List[OrderPlan]) -> None:
        for plan in orders:
            self.logger.emit(
                "order_plan",
                signal_id=signal_id,
                symbol=plan.symbol,
                pool_id=plan.pool_id,
                pool_capital_before_split=plan.average_allocation * len(orders),
                average_allocation=plan.average_allocation,
                symbol_cap=plan.symbol_cap,
                requested_capital=plan.requested_capital,
                cap_applied=plan.cap_applied,
                allocated_capital=plan.allocated_capital,
                price=plan.price,
                quantity=plan.quantity,
                notional=plan.notional,
                leverage=plan.leverage,
                margin_mode=plan.margin_mode,
                exchange_delivery_time_ms=plan.exchange_delivery_time_ms,
                exchange_delivery_time=timestamp_ms_to_iso(plan.exchange_delivery_time_ms),
            )
            self.logger.emit(
                "order_submit_request",
                signal_id=signal_id,
                symbol=plan.symbol,
                pool_id=plan.pool_id,
                side="SELL",
                order_type="MARKET",
                quantity=plan.quantity,
                dry_run=self.config.dry_run,
                exchange_mode=self.config.exchange_mode,
                leverage=plan.leverage,
                margin_mode=plan.margin_mode,
                reduce_only=False,
                exchange_delivery_time_ms=plan.exchange_delivery_time_ms,
                exchange_delivery_time=timestamp_ms_to_iso(plan.exchange_delivery_time_ms),
            )

    def handle_signal(
        self,
        announcement_id: str,
        announcement_title: str,
        announcement_url: str,
        announcement_publish_time: str,
        matched_keywords: List[str],
        matched_symbols: List[str],
    ) -> Dict[str, object]:
        try:
            snapshot = self._load_account_snapshot()
            pool_rebalanced, pool_allocations = self._maybe_rebalance_pools(snapshot)
        except Exception as exc:
            self.logger.emit(
                "signal_skipped",
                trigger_time=announcement_publish_time,
                announcement_title=announcement_title,
                announcement_url=announcement_url,
                announcement_publish_time=announcement_publish_time,
                matched_keywords=matched_keywords,
                matched_symbols=matched_symbols,
                selected_pool_id=None,
                pool_capital=0.0,
                symbol_count=len(matched_symbols),
                reason="account_snapshot_unavailable",
                error=str(exc),
            )
            return {"status": "skipped", "reason": "account_snapshot_unavailable", "error": str(exc)}

        allocation = self.allocator.choose_pool(announcement_id)
        self._emit_capital_snapshot(
            snapshot=snapshot,
            pool_allocations=pool_allocations,
            announcement_title=announcement_title,
            announcement_publish_time=announcement_publish_time,
            matched_symbols=matched_symbols,
            pool_rebalanced=pool_rebalanced,
            selected_pool_id=allocation.pool_id,
        )

        if not allocation.pool_id:
            self.logger.emit(
                "signal_skipped",
                trigger_time=announcement_publish_time,
                announcement_title=announcement_title,
                announcement_url=announcement_url,
                announcement_publish_time=announcement_publish_time,
                matched_keywords=matched_keywords,
                matched_symbols=matched_symbols,
                selected_pool_id=None,
                pool_capital=0.0,
                symbol_count=len(matched_symbols),
                reason=allocation.reason,
            )
            return {"status": allocation.status, "reason": allocation.reason}

        if not matched_symbols:
            self.allocator.release_pool(allocation.pool_id)
            self.logger.emit(
                "signal_skipped",
                trigger_time=announcement_publish_time,
                announcement_title=announcement_title,
                announcement_url=announcement_url,
                announcement_publish_time=announcement_publish_time,
                matched_keywords=matched_keywords,
                matched_symbols=matched_symbols,
                selected_pool_id=allocation.pool_id,
                pool_capital=allocation.pool_capital,
                symbol_count=0,
                reason="no_matched_symbols",
            )
            return {"status": "skipped", "reason": "no_matched_symbols", "pool_id": allocation.pool_id}

        signal = self.planner.build_signal(
            announcement_id=announcement_id,
            announcement_title=announcement_title,
            announcement_url=announcement_url,
            announcement_publish_time=announcement_publish_time,
            matched_keywords=matched_keywords,
            matched_symbols=matched_symbols,
            pool_id=allocation.pool_id,
            pool_capital=allocation.pool_capital,
            strategy_total_capital=snapshot.strategy_total_capital,
            available_balance=snapshot.available_balance,
            capital_basis=snapshot.capital_basis,
            pool_rebalanced=pool_rebalanced,
        )
        signal.notes = {
            "pool_allocations": pool_allocations,
            "available_balance": snapshot.available_balance,
            "total_margin_balance": snapshot.total_margin_balance,
            "total_wallet_balance": snapshot.total_wallet_balance,
            "total_unrealized_profit": snapshot.total_unrealized_profit,
            "symbol_delivery_times": {},
        }
        self.store.upsert_signal(signal)
        self.logger.emit(
            "signal_triggered",
            trigger_time=signal.triggered_at,
            announcement_title=signal.announcement_title,
            announcement_url=signal.announcement_url,
            announcement_publish_time=signal.announcement_publish_time,
            matched_keywords=signal.matched_keywords,
            matched_symbols=signal.matched_symbols,
            selected_pool_id=signal.pool_id,
            pool_capital=signal.pool_capital,
            symbol_count=signal.symbol_count,
            strategy_total_capital=signal.strategy_total_capital,
            available_balance=signal.available_balance,
            capital_basis=signal.capital_basis,
            pool_rebalanced=signal.pool_rebalanced,
        )

        orders = self.planner.plan_orders(signal, self.exchange)
        signal.notes["symbol_delivery_times"] = {plan.symbol: plan.exchange_delivery_time_ms for plan in orders}
        self.store.upsert_signal(signal)
        if not orders:
            self.allocator.release_pool(signal.pool_id)
            self.store.update_signal(signal.signal_id, status="skipped")
            self.logger.emit(
                "signal_skipped",
                trigger_time=signal.triggered_at,
                announcement_title=signal.announcement_title,
                announcement_url=signal.announcement_url,
                announcement_publish_time=signal.announcement_publish_time,
                matched_keywords=signal.matched_keywords,
                matched_symbols=signal.matched_symbols,
                selected_pool_id=signal.pool_id,
                pool_capital=signal.pool_capital,
                symbol_count=signal.symbol_count,
                reason="no_order_plans",
            )
            return {"status": "skipped", "reason": "no_order_plans", "signal_id": signal.signal_id}

        self._emit_order_plans(signal.signal_id, orders)
        execution_error = None
        try:
            positions = self.engine.execute(orders)
        except ExecutionBatchError as exc:
            positions = exc.opened_records
            execution_error = str(exc)

        if not positions:
            self.allocator.release_pool(signal.pool_id)
            self.store.update_signal(signal.signal_id, status="failed")
            self.logger.emit(
                "signal_failed",
                trigger_time=signal.triggered_at,
                signal_id=signal.signal_id,
                announcement_title=signal.announcement_title,
                pool_id=signal.pool_id,
                error=execution_error or "order_execution_failed",
            )
            return {"status": "failed", "signal_id": signal.signal_id, "reason": execution_error or "order_execution_failed"}

        self.lifecycle.register_signal(signal.signal_id, signal.announcement_title, signal.pool_id, signal.pool_capital, len(positions))
        signal_status = "opened"
        if execution_error:
            signal_status = "partial_opened"
            self.logger.emit(
                "order_batch_error",
                signal_id=signal.signal_id,
                announcement_title=signal.announcement_title,
                error=execution_error,
                opened_positions=len(positions),
                planned_positions=len(orders),
            )
        self.store.update_signal(signal.signal_id, status=signal_status)

        plan_by_symbol = {plan.symbol: plan for plan in orders}
        for position in positions:
            plan = plan_by_symbol.get(position.symbol)
            self.logger.emit(
                "order_opened",
                order_time=position.open_time,
                signal_id=position.signal_id,
                symbol=position.symbol,
                side=position.side,
                requested_capital=plan.requested_capital if plan else position.allocated_capital,
                allocated_capital=position.allocated_capital,
                average_allocation=plan.average_allocation if plan else None,
                symbol_cap=plan.symbol_cap if plan else None,
                cap_applied=plan.cap_applied if plan else None,
                leverage=position.leverage,
                margin_mode=plan.margin_mode if plan else "CROSSED",
                entry_price=position.entry_price,
                quantity=position.quantity,
                exchange_delivery_time_ms=position.exchange_delivery_time_ms,
                exchange_delivery_time=timestamp_ms_to_iso(position.exchange_delivery_time_ms),
                dry_run=self.config.dry_run,
                live_mode=self.config.live_trading_enabled and not self.config.dry_run,
                related_announcement_title=position.announcement_title,
                related_pool_id=position.pool_id,
            )

        open_positions = self.store.list_open_positions()
        self.logger.emit(
            "position_snapshot",
            snapshot_time=positions[-1].open_time if positions else signal.triggered_at,
            signal_id=signal.signal_id,
            announcement_title=signal.announcement_title,
            pool_id=signal.pool_id,
            open_position_count=len(open_positions),
            open_positions=[
                {
                    "position_id": pos["position_id"],
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "status": pos["status"],
                    "quantity": pos["quantity"],
                    "entry_price": pos["entry_price"],
                    "allocated_capital": pos["allocated_capital"],
                    "pnl": pos["pnl"],
                    "pnl_pct": pos["pnl_pct"],
                    "open_time": pos["open_time"],
                    "exchange_delivery_time_ms": pos.get("exchange_delivery_time_ms"),
                    "exchange_delivery_time": timestamp_ms_to_iso(pos.get("exchange_delivery_time_ms")),
                    "close_time": pos["close_time"],
                    "close_price": pos.get("close_price"),
                    "close_reason": pos["close_reason"],
                }
                for pos in open_positions
            ],
        )
        return {"status": signal_status, "signal_id": signal.signal_id, "pool_id": signal.pool_id, "positions": positions}

    def monitor_positions_once(self) -> List[Dict[str, object]]:
        results = self.monitor.scan_open_positions()
        for result in results:
            if result.get("closed"):
                pos = self.store.get_position(result["position_id"])
                if pos:
                    self.lifecycle.mark_position_closed(pos["signal_id"], close_pnl=float(pos.get("pnl", 0.0)))
        return results

    def close(self) -> None:
        self.logger.close()
