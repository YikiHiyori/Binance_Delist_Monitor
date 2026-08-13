import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.capital_allocator import CapitalAllocator
from binance_delist_monitor.config import AppConfig
from binance_delist_monitor.exchange_client import MockExchangeClient
from binance_delist_monitor.position_store import PositionStore
from binance_delist_monitor.signal_planner import SignalToOrderPlanner
from binance_delist_monitor.trade_models import PositionRecord
from binance_delist_monitor.trade_orchestrator import TradeOrchestrator


def make_config(tmpdir: Path) -> AppConfig:
    return AppConfig(
        log_file=tmpdir / "events.log",
        state_file=tmpdir / "state.json",
        trading_db_file=tmpdir / "trading.sqlite3",
        dry_run=True,
        live_trading_enabled=False,
        exchange_mode="mock",
        total_capital=1000.0,
        leverage=1,
        max_active_signal_pools=2,
        allow_signal_queue=False,
        take_profit_pct=0.45,
        stop_loss_pct=0.08,
        enable_take_profit=True,
        enable_stop_loss=False,
        price_poll_interval_seconds=0,
    )


class CapitalAllocatorTests(unittest.TestCase):
    def test_pool_allocation_prefers_a_then_b_and_skips_third(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            store = PositionStore(tmpdir / "store.sqlite3")
            allocator = CapitalAllocator(1000.0, 2, False, store)

            first = allocator.choose_pool("sig-1")
            second = allocator.choose_pool("sig-2")
            third = allocator.choose_pool("sig-3")

            self.assertEqual(first.pool_id, "A")
            self.assertAlmostEqual(first.pool_capital, 600.0)
            self.assertEqual(second.pool_id, "B")
            self.assertAlmostEqual(second.pool_capital, 400.0)
            self.assertIsNone(third.pool_id)
            self.assertEqual(third.status, "skipped")

    def test_rebase_splits_60_40_only_when_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            store = PositionStore(tmpdir / "store.sqlite3")
            allocator = CapitalAllocator(1000.0, 2, False, store)

            allocations = allocator.rebase_pools(2000.0)
            self.assertEqual(allocations, {"A": 1200.0, "B": 800.0})

            allocator.choose_pool("sig-1")
            with self.assertRaisesRegex(RuntimeError, "idle"):
                allocator.rebase_pools(2500.0)

    def test_restart_recovery_preserves_pool_occupancy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            store = PositionStore(tmpdir / "store.sqlite3")
            allocator = CapitalAllocator(1000.0, 2, False, store)
            allocator.choose_pool("sig-1")
            record = PositionRecord(
                position_id="pos-1",
                trade_id="trade-1",
                signal_id="sig-1",
                announcement_id="ann-1",
                announcement_title="Delist A",
                announcement_url="http://example.test",
                symbol="AAAUSDT",
                side="SHORT",
                pool_id="A",
                allocated_capital=200.0,
                leverage=1,
                entry_price=100.0,
                quantity=2.0,
                status="OPEN",
                open_time="2026-01-01T00:00:00",
            )
            store.insert_position(record)

            restarted = CapitalAllocator(1000.0, 2, False, store)
            pools = {pool["pool_id"]: pool for pool in restarted.pool_summary()}
            self.assertEqual(pools["A"]["status"], "occupied")
            self.assertEqual(pools["A"]["announcement_key"], "sig-1")
            self.assertEqual(pools["B"]["status"], "idle")


class PlannerTests(unittest.TestCase):
    def test_single_symbol_cap_applies(self):
        planner = SignalToOrderPlanner(leverage=1)
        exchange = MockExchangeClient(default_price=100.0, account_balance=1000.0)
        exchange.set_price("AAAUSDT", 100.0)
        exchange.set_symbol_metadata("AAAUSDT", status="TRADING", delivery_time_ms=1767225600000)
        signal = planner.build_signal(
            announcement_id="sig-1",
            announcement_title="Delist AAA",
            announcement_url="http://example.test",
            announcement_publish_time="2026-01-01T00:00:00",
            matched_keywords=["perpetual", "delist"],
            matched_symbols=["AAAUSDT"],
            pool_id="A",
            pool_capital=600.0,
            strategy_total_capital=1000.0,
            available_balance=950.0,
            capital_basis="totalMarginBalance",
            pool_rebalanced=True,
        )

        plans = planner.plan_orders(signal, exchange)
        self.assertEqual(len(plans), 1)
        self.assertAlmostEqual(plans[0].average_allocation, 600.0)
        self.assertAlmostEqual(plans[0].symbol_cap, 200.0)
        self.assertAlmostEqual(plans[0].requested_capital, 200.0)
        self.assertAlmostEqual(plans[0].allocated_capital, 200.0)
        self.assertTrue(plans[0].cap_applied)
        self.assertAlmostEqual(plans[0].quantity, 2.0)
        self.assertEqual(plans[0].exchange_delivery_time_ms, 1767225600000)

    def test_second_pool_average_can_stay_below_cap(self):
        planner = SignalToOrderPlanner(leverage=1)
        exchange = MockExchangeClient(default_price=100.0, account_balance=1000.0)
        for symbol in ["AUSDT", "BUSDT", "CUSDT", "DUSDT"]:
            exchange.set_price(symbol, 100.0)
        signal = planner.build_signal(
            announcement_id="sig-2",
            announcement_title="Delist Four",
            announcement_url="http://example.test",
            announcement_publish_time="2026-01-01T00:00:00",
            matched_keywords=["perpetual", "delist"],
            matched_symbols=["AUSDT", "BUSDT", "CUSDT", "DUSDT"],
            pool_id="B",
            pool_capital=400.0,
            strategy_total_capital=1000.0,
            available_balance=930.0,
            capital_basis="totalMarginBalance",
            pool_rebalanced=False,
        )

        plans = planner.plan_orders(signal, exchange)
        self.assertEqual(len(plans), 4)
        self.assertTrue(all(plan.cap_applied is False for plan in plans))
        self.assertTrue(all(plan.requested_capital == 100.0 for plan in plans))


class TradeOrchestratorTests(unittest.TestCase):
    def test_two_pools_then_skip_third_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price("A1USDT", 100.0)
                orchestrator.exchange.set_price("B1USDT", 100.0)
                orchestrator.exchange.set_price("C1USDT", 100.0)

                first = orchestrator.handle_signal(
                    announcement_id="sig-a",
                    announcement_title="Delist A",
                    announcement_url="http://example.test/a",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["A1USDT"],
                )
                second = orchestrator.handle_signal(
                    announcement_id="sig-b",
                    announcement_title="Delist B",
                    announcement_url="http://example.test/b",
                    announcement_publish_time="2026-01-01T00:01:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["B1USDT"],
                )
                third = orchestrator.handle_signal(
                    announcement_id="sig-c",
                    announcement_title="Delist C",
                    announcement_url="http://example.test/c",
                    announcement_publish_time="2026-01-01T00:02:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["C1USDT"],
                )

                self.assertEqual(first["pool_id"], "A")
                self.assertEqual(second["pool_id"], "B")
                self.assertEqual(third["status"], "skipped")
                self.assertEqual(third["reason"], "no_available_pool")
            finally:
                orchestrator.close()

    def test_rebalance_after_all_positions_closed_uses_new_account_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price_series("TP1USDT", [100.0, 50.0])

                first = orchestrator.handle_signal(
                    announcement_id="sig-1",
                    announcement_title="Delist TP1",
                    announcement_url="http://example.test/1",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["TP1USDT"],
                )
                self.assertEqual(first["status"], "opened")
                monitor_results = orchestrator.monitor_positions_once()
                self.assertTrue(monitor_results[0]["closed"])
                self.assertEqual(len(orchestrator.store.list_open_positions()), 0)

                orchestrator.exchange.set_account_snapshot(total_margin_balance=1200.0, available_balance=1100.0)
                orchestrator.exchange.set_price("TP2USDT", 100.0)
                second = orchestrator.handle_signal(
                    announcement_id="sig-2",
                    announcement_title="Delist TP2",
                    announcement_url="http://example.test/2",
                    announcement_publish_time="2026-01-01T01:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["TP2USDT"],
                )

                self.assertEqual(second["pool_id"], "A")
                pools = {pool["pool_id"]: pool for pool in orchestrator.store.get_pools()}
                self.assertAlmostEqual(pools["A"]["allocated_capital"], 720.0)
                self.assertAlmostEqual(pools["B"]["allocated_capital"], 480.0)
                self.assertAlmostEqual(second["positions"][0].allocated_capital, 240.0)
            finally:
                orchestrator.close()

    def test_sync_detected_closed_releases_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price("SYNCUSDT", 80.0)

                result = orchestrator.handle_signal(
                    announcement_id="sig-sync",
                    announcement_title="Delist Sync",
                    announcement_url="http://example.test/sync",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["SYNCUSDT"],
                )
                orchestrator.exchange.positions.pop("SYNCUSDT", None)

                scan = orchestrator.monitor_positions_once()
                self.assertTrue(scan[0]["closed"])
                self.assertEqual(scan[0]["close_reason"], "sync_detected_closed")
                self.assertEqual(len(orchestrator.store.list_open_positions()), 0)
                self.assertEqual(orchestrator.store.get_pool("A")["status"], "idle")
                self.assertEqual(result["pool_id"], "A")
            finally:
                orchestrator.close()

    def test_exchange_delist_closed_when_symbol_is_no_longer_tradable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price("DELISTUSDT", 100.0)
                orchestrator.exchange.set_symbol_metadata("DELISTUSDT", status="TRADING", delivery_time_ms=1767225600000)

                orchestrator.handle_signal(
                    announcement_id="sig-delist",
                    announcement_title="Delist Symbol",
                    announcement_url="http://example.test/delist",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["DELISTUSDT"],
                )
                orchestrator.exchange.positions.pop("DELISTUSDT", None)
                orchestrator.exchange.set_symbol_metadata("DELISTUSDT", status="SETTLING", delivery_time_ms=1704067200000)
                orchestrator.exchange.append_income("DELISTUSDT", 45.0, income_type="DELIVERED_SETTELMENT")
                orchestrator.exchange.append_income("DELISTUSDT", -1.5, income_type="COMMISSION")

                scan = orchestrator.monitor_positions_once()
                self.assertTrue(scan[0]["closed"])
                self.assertEqual(scan[0]["close_reason"], "exchange_delist_closed")
                self.assertAlmostEqual(scan[0]["pnl"], 43.5)
                position = orchestrator.store.get_position(scan[0]["position_id"])
                self.assertIsNone(position["close_price"])
                self.assertAlmostEqual(position["pnl"], 43.5)
            finally:
                orchestrator.close()

    def test_delist_reconcile_waits_for_income_history_instead_of_entry_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price("WAITUSDT", 100.0)
                orchestrator.exchange.set_symbol_metadata("WAITUSDT", status="TRADING", delivery_time_ms=1767225600000)

                result = orchestrator.handle_signal(
                    announcement_id="sig-wait",
                    announcement_title="Delist Wait",
                    announcement_url="http://example.test/wait",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["WAITUSDT"],
                )
                self.assertEqual(result["status"], "opened")

                orchestrator.exchange.positions.pop("WAITUSDT", None)
                orchestrator.exchange.set_symbol_metadata("WAITUSDT", status="SETTLING", delivery_time_ms=1704067200000)

                scan = orchestrator.monitor_positions_once()
                self.assertFalse(scan[0]["closed"])
                self.assertEqual(scan[0]["trigger_status"], "awaiting_income_history")

                position = orchestrator.store.get_position(result["positions"][0].position_id)
                self.assertEqual(position["status"], "OPEN")
                self.assertIsNone(position["close_price"])
            finally:
                orchestrator.close()

    def test_mock_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price_series("X1USDT", [100.0, 50.0])
                orchestrator.exchange.set_price_series("X2USDT", [100.0, 50.0])

                result = orchestrator.handle_signal(
                    announcement_id="sig-e2e",
                    announcement_title="Delist E2E",
                    announcement_url="http://example.test/e2e",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["X1USDT", "X2USDT"],
                )
                self.assertEqual(result["status"], "opened")

                scan = orchestrator.monitor_positions_once()
                self.assertTrue(all(item["closed"] for item in scan))
                self.assertEqual(len(orchestrator.store.list_open_positions()), 0)
                self.assertEqual(orchestrator.store.get_pool("A")["status"], "idle")
            finally:
                orchestrator.close()

    def test_position_snapshot_logged_after_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            config = make_config(tmpdir)
            orchestrator = TradeOrchestrator(config)
            try:
                orchestrator.exchange.set_price("SNAPUSDT", 100.0)

                orchestrator.handle_signal(
                    announcement_id="sig-snap",
                    announcement_title="Delist SNAP",
                    announcement_url="http://example.test/snap",
                    announcement_publish_time="2026-01-01T00:00:00",
                    matched_keywords=["perpetual", "delist"],
                    matched_symbols=["SNAPUSDT"],
                )
            finally:
                orchestrator.close()
            log_text = config.log_file.read_text(encoding="utf-8")
            self.assertIn('"event_type": "position_snapshot"', log_text)
            self.assertIn('"open_position_count": 1', log_text)
            self.assertIn('"symbol": "SNAPUSDT"', log_text)


if __name__ == "__main__":
    unittest.main()
