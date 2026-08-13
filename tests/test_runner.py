import sys
import unittest
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.config import AppConfig
from binance_delist_monitor.heartbeat import Heartbeat
from binance_delist_monitor.models import AnnouncementDetail, AnnouncementItem
from binance_delist_monitor.runner import run_once, run_testnet_smoke, validate_runtime_config
from binance_delist_monitor.state import StateStore


class RunnerConfigTests(unittest.TestCase):
    def test_live_mode_requires_api_credentials(self):
        config = AppConfig(
            exchange_mode="live",
            dry_run=False,
            live_trading_enabled=True,
            binance_api_key="",
            binance_api_secret="",
        )
        with self.assertRaisesRegex(RuntimeError, "BINANCE_API_KEY"):
            validate_runtime_config(config)

    def test_live_mode_requires_trading_flags(self):
        config = AppConfig(
            exchange_mode="live",
            dry_run=True,
            live_trading_enabled=False,
            binance_api_key="key",
            binance_api_secret="secret",
        )
        with self.assertRaisesRegex(RuntimeError, "DRY_RUN=false"):
            validate_runtime_config(config)


class _FakeExchange:
    def get_price(self, symbol):
        return 100.0


class _FakeOrchestrator:
    def __init__(self, result):
        self.exchange = _FakeExchange()
        self._result = result

    def handle_signal(self, **kwargs):
        return dict(self._result)

    def monitor_positions_once(self):
        return []

    def close(self):
        return None


class _FakeAnnouncementClient:
    items = []

    def __init__(self, *args, **kwargs):
        return None

    def fetch_items(self, **kwargs):
        return list(self.items)

    def build_official_url(self, item):
        return f"https://example.invalid/{item.code}"


class _FakeMirrorClient:
    def __init__(self, *args, **kwargs):
        return None


class _FakeContractUniverse:
    symbols = []

    def __init__(self, *args, **kwargs):
        return None

    def fetch_symbols(self):
        return list(self.symbols)


class _FakeTradeExecutor:
    def __init__(self):
        self.calls = []

    def handle_signal(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"status": "opened", "signal_id": "sig-1", "pool_id": "A", "positions": [{"symbol": "VINEUSDT"}]}

    def monitor_positions_once(self):
        return []


class RunnerSmokeTests(unittest.TestCase):
    def test_testnet_smoke_surfaces_signal_failure_before_open(self):
        config = AppConfig(
            exchange_mode="testnet",
            dry_run=False,
            live_trading_enabled=True,
            binance_api_key="key",
            binance_api_secret="secret",
        )
        logger = logging.getLogger("test_runner_smoke")
        logger.handlers[:] = []
        logger.addHandler(logging.NullHandler())

        with patch("binance_delist_monitor.runner.TradeOrchestrator", return_value=_FakeOrchestrator({"status": "skipped", "reason": "account_snapshot_unavailable"})):
            with self.assertRaisesRegex(RuntimeError, "status=skipped reason=account_snapshot_unavailable"):
                run_testnet_smoke(config, logger, "BTCUSDT")


class RunnerScanTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_runner_scan")
        self.logger.handlers[:] = []
        self.logger.addHandler(logging.NullHandler())

    def test_run_once_retries_candidate_until_detail_arrives(self):
        item = AnnouncementItem(
            article_id=1276,
            code="ba5d61807b474b0ca9f40250e7fa782c",
            title="Binance Futures Will Delist USDⓈ-M Multiple Perpetual Contracts (2026-04-28)",
            release_ts=int(datetime(2026, 4, 24, 11, 15, 13).timestamp() * 1000),
            catalog_name="Delisting",
        )
        detail = AnnouncementDetail(
            title=item.title,
            publish_time=item.release_time,
            url="https://www.binance.com/en/support/announcement/detail/ba5d61807b474b0ca9f40250e7fa782c",
            full_text=(
                "Binance Futures will close all positions and conduct an automatic settlement on "
                "USDS-M VINEUSDT and AIUSDT Perpetual Contracts at 2026-04-28 10:00 (UTC)."
            ),
            body_source="binance_html",
        )
        _FakeAnnouncementClient.items = [item]
        _FakeContractUniverse.symbols = ["VINEUSDT", "AIUSDT"]

        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                state_file=Path(tmp) / "state.json",
                trading_db_file=Path(tmp) / "trading.sqlite3",
                log_file=Path(tmp) / "monitor.log",
            )
            store = StateStore(config.state_file)
            executor = _FakeTradeExecutor()
            with patch("binance_delist_monitor.runner.BinanceAnnouncementClient", _FakeAnnouncementClient), patch(
                "binance_delist_monitor.runner.MirrorAnnouncementClient", _FakeMirrorClient
            ), patch("binance_delist_monitor.runner.ContractUniverse", _FakeContractUniverse), patch(
                "binance_delist_monitor.runner.pick_detail", return_value=None
            ):
                signals = run_once(config, self.logger, store, Heartbeat(), executor)

            self.assertEqual(signals, 0)
            self.assertFalse(store.is_processed(item.dedupe_key))
            self.assertIn(item.dedupe_key, store.state.pending_details)
            self.assertEqual(executor.calls, [])

            store.state.pending_details[item.dedupe_key]["next_retry_at"] = (datetime.utcnow() - timedelta(seconds=1)).isoformat()

            with patch("binance_delist_monitor.runner.BinanceAnnouncementClient", _FakeAnnouncementClient), patch(
                "binance_delist_monitor.runner.MirrorAnnouncementClient", _FakeMirrorClient
            ), patch("binance_delist_monitor.runner.ContractUniverse", _FakeContractUniverse), patch(
                "binance_delist_monitor.runner.pick_detail", return_value=detail
            ):
                signals = run_once(config, self.logger, store, Heartbeat(), executor)

            self.assertEqual(signals, 1)
            self.assertTrue(store.is_processed(item.dedupe_key))
            self.assertNotIn(item.dedupe_key, store.state.pending_details)
            self.assertEqual(len(executor.calls), 1)
            self.assertEqual(executor.calls[0]["matched_symbols"], ["VINEUSDT", "AIUSDT"])

    def test_run_once_skips_margin_delist_title_even_with_futures_words_in_body(self):
        item = AnnouncementItem(
            article_id=1389,
            code="06175ada1556867e",
            title="Binance Margin And Binance Loans Will Delist AEUR and AI on 2026-05-22",
            release_ts=int(datetime(2026, 5, 19, 3, 0, 9).timestamp() * 1000),
            catalog_name="Delisting",
        )
        detail = AnnouncementDetail(
            title=item.title,
            publish_time=item.release_time,
            url="https://www.binance.com/en/support/announcement/detail/06175ada1556867e",
            full_text=(
                "Please Note: For futures perpetual contracts, please refer to the relevant futures announcements. "
                "Any remaining collateral assets will be sold for USDT after the delisting is completed."
            ),
            body_source="binance_html",
        )
        _FakeAnnouncementClient.items = [item]
        _FakeContractUniverse.symbols = ["AIUSDT", "龙虾USDT", "币安人生USDT"]

        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                state_file=Path(tmp) / "state.json",
                trading_db_file=Path(tmp) / "trading.sqlite3",
                log_file=Path(tmp) / "monitor.log",
            )
            store = StateStore(config.state_file)
            executor = _FakeTradeExecutor()
            with patch("binance_delist_monitor.runner.BinanceAnnouncementClient", _FakeAnnouncementClient), patch(
                "binance_delist_monitor.runner.MirrorAnnouncementClient", _FakeMirrorClient
            ), patch("binance_delist_monitor.runner.ContractUniverse", _FakeContractUniverse), patch(
                "binance_delist_monitor.runner.pick_detail", return_value=detail
            ):
                signals = run_once(config, self.logger, store, Heartbeat(), executor)

            self.assertEqual(signals, 0)
            self.assertTrue(store.is_processed(item.dedupe_key))
            self.assertEqual(executor.calls, [])

    def test_run_once_rejects_untrusted_detail_source(self):
        item = AnnouncementItem(
            article_id=1276,
            code="ba5d61807b474b0ca9f40250e7fa782c",
            title="Binance Futures Will Delist USDⓈ-M Multiple Perpetual Contracts (2026-04-28)",
            release_ts=int(datetime(2026, 4, 24, 11, 15, 13).timestamp() * 1000),
            catalog_name="Delisting",
        )
        detail = AnnouncementDetail(
            title=item.title,
            publish_time=item.release_time,
            url="https://cache.bwe-ws.com/bn-1276",
            full_text="Binance Futures will delist USDⓈ-M VINEUSDT Perpetual Contracts.",
            body_source="mirror_html",
        )
        _FakeAnnouncementClient.items = [item]
        _FakeContractUniverse.symbols = ["VINEUSDT"]

        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                state_file=Path(tmp) / "state.json",
                trading_db_file=Path(tmp) / "trading.sqlite3",
                log_file=Path(tmp) / "monitor.log",
            )
            store = StateStore(config.state_file)
            executor = _FakeTradeExecutor()
            with patch("binance_delist_monitor.runner.BinanceAnnouncementClient", _FakeAnnouncementClient), patch(
                "binance_delist_monitor.runner.MirrorAnnouncementClient", _FakeMirrorClient
            ), patch("binance_delist_monitor.runner.ContractUniverse", _FakeContractUniverse), patch(
                "binance_delist_monitor.runner.pick_detail", return_value=detail
            ):
                signals = run_once(config, self.logger, store, Heartbeat(), executor)

            self.assertEqual(signals, 0)
            self.assertTrue(store.is_processed(item.dedupe_key))
            self.assertEqual(executor.calls, [])

    def test_run_once_processes_non_candidate_without_detail_retry(self):
        item = AnnouncementItem(
            article_id=1,
            code="284add8252634349920b1e0c5f92563d",
            title="OpenGradient Trading Competition: Trade OpenGradient (OPG) and Share $200K Worth of Rewards",
            release_ts=int(datetime(2026, 4, 24, 11, 0, 0).timestamp() * 1000),
            catalog_name="Latest Activities",
        )
        _FakeAnnouncementClient.items = [item]
        _FakeContractUniverse.symbols = ["BTCUSDT"]

        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                state_file=Path(tmp) / "state.json",
                trading_db_file=Path(tmp) / "trading.sqlite3",
                log_file=Path(tmp) / "monitor.log",
            )
            store = StateStore(config.state_file)
            executor = _FakeTradeExecutor()
            with patch("binance_delist_monitor.runner.BinanceAnnouncementClient", _FakeAnnouncementClient), patch(
                "binance_delist_monitor.runner.MirrorAnnouncementClient", _FakeMirrorClient
            ), patch("binance_delist_monitor.runner.ContractUniverse", _FakeContractUniverse), patch(
                "binance_delist_monitor.runner.pick_detail", return_value=None
            ):
                signals = run_once(config, self.logger, store, Heartbeat(), executor)

            self.assertEqual(signals, 0)
            self.assertTrue(store.is_processed(item.dedupe_key))
            self.assertNotIn(item.dedupe_key, store.state.pending_details)
            self.assertEqual(executor.calls, [])


if __name__ == "__main__":
    unittest.main()
