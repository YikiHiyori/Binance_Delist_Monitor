from __future__ import annotations

import logging
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .announcements import BinanceAnnouncementClient, MirrorAnnouncementClient
from .config import load_config
from .contracts import ContractUniverse, sanitize_contract_symbols
from .heartbeat import Heartbeat
from .http_client import HttpClient
from .matching import looks_like_supported_futures_delist_title, match_announcement
from .state import StateStore
from .trade_executor import TradeExecutor
from .trade_orchestrator import TradeOrchestrator
from .utils import clean_html_text, join_nonempty


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("binance_delist_monitor")
    logger.setLevel(logging.INFO)
    logger.handlers[:] = []
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.setLevel(logging.INFO)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    return logger


def summarize(text: str, limit: int = 280) -> str:
    text = clean_html_text(text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def ensure_contracts(contract_source: ContractUniverse, state: StateStore, ttl_seconds: int, logger: logging.Logger) -> List[str]:
    cache = state.get_contract_cache()
    raw_symbols = cache.get("symbols") or []
    symbols = sanitize_contract_symbols(raw_symbols)
    fetched_at = cache.get("fetched_at")
    if symbols != raw_symbols:
        state.set_contract_cache(symbols, fetched_at=fetched_at)
    if symbols and fetched_at:
        try:
            fetched = datetime.fromisoformat(str(fetched_at))
            if fetched.tzinfo is not None:
                fetched = fetched.astimezone(timezone.utc).replace(tzinfo=None)
            age = (datetime.utcnow() - fetched).total_seconds()
            if age < ttl_seconds:
                return symbols
        except Exception:
            pass
    fetched = sanitize_contract_symbols(contract_source.fetch_symbols())
    if fetched:
        state.set_contract_cache(fetched)
        try:
            state.save()
        except Exception as exc:
            logger.warning("contract cache save failed: %s", exc)
        return fetched
    if symbols:
        return symbols
    return []


def pick_detail(
    official_client: BinanceAnnouncementClient,
    mirror_client: MirrorAnnouncementClient,
    item,
    *,
    allow_mirror: bool = False,
) -> Optional[object]:
    detail = official_client.fetch_official_detail(item)
    if detail:
        return detail
    if not allow_mirror:
        return None
    return mirror_client.fetch_detail(item.title)


def should_retry_without_detail(item) -> bool:
    return looks_like_supported_futures_delist_title(item.title)


def emit_signal(logger: logging.Logger, title: str, url: str, publish_time, keywords, symbols: List[str], summary: str) -> None:
    logger.info("[DELIST SIGNAL]")
    logger.info("title: %s", title)
    logger.info("url: %s", url)
    logger.info("time: %s", publish_time.isoformat())
    logger.info("matched_keywords: %s", ", ".join(keywords))
    logger.info("symbols: %s", ", ".join(symbols) if symbols else "(none)")
    logger.info("summary: %s", summary)


def validate_runtime_config(config) -> None:
    valid_modes = {"mock", "paper", "testnet", "live"}
    if config.exchange_mode not in valid_modes:
        raise RuntimeError(f"invalid EXCHANGE_MODE={config.exchange_mode!r}; expected one of {sorted(valid_modes)}")

    if config.exchange_mode in {"testnet", "live"}:
        missing = []
        if not config.binance_api_key:
            missing.append("BINANCE_API_KEY")
        if not config.binance_api_secret:
            missing.append("BINANCE_API_SECRET")
        if missing:
            raise RuntimeError(
                "live-capable mode requires non-empty " + ", ".join(missing) + "; fill them in .env before starting"
            )

    if config.exchange_mode in {"testnet", "live"} and config.dry_run:
        raise RuntimeError("live-capable mode requires DRY_RUN=false")

    if config.exchange_mode in {"testnet", "live"} and not config.live_trading_enabled:
        raise RuntimeError("live-capable mode requires LIVE_TRADING_ENABLED=true")


def run_once(config, logger: logging.Logger, state: StateStore, heartbeat: Heartbeat, trade_executor: TradeExecutor) -> int:
    http = HttpClient(timeout_seconds=config.http_timeout_seconds, verify_ssl=config.verify_ssl)
    announcement_client = BinanceAnnouncementClient(http, config.official_list_url)
    mirror_client = MirrorAnnouncementClient(http, config.mirror_latest_url, config.mirror_article_url_template)
    contract_source = ContractUniverse(
        http,
        futures_url=config.futures_exchange_info_url,
    )

    symbols = ensure_contracts(contract_source, state, config.contract_cache_ttl_seconds, logger)
    logger.info("loaded %s contract symbols", len(symbols))

    items = announcement_client.fetch_items(max_pages=config.announcement_max_pages, page_size=config.announcement_page_size)
    logger.info("fetched %s announcement items", len(items))

    signals = 0
    for item in items:
        if state.is_processed(item.dedupe_key):
            continue
        if not state.is_detail_retry_due(item.dedupe_key):
            continue
        if not looks_like_supported_futures_delist_title(item.title):
            state.mark_processed(item.dedupe_key)
            continue
        detail = pick_detail(announcement_client, mirror_client, item, allow_mirror=False)
        if detail is None:
            if should_retry_without_detail(item):
                pending = state.mark_detail_retry(
                    item.dedupe_key,
                    base_delay_seconds=max(30, int(config.poll_interval_seconds)),
                    max_delay_seconds=max(300, int(config.poll_interval_seconds) * 10),
                )
                logger.info(
                    "detail unavailable; scheduled retry title=%s retry_count=%s next_retry_at=%s",
                    item.title,
                    pending.get("retry_count"),
                    pending.get("next_retry_at"),
                )
                continue
            state.mark_processed(item.dedupe_key)
            continue
        if detail.body_source != "binance_html":
            logger.info(
                "candidate rejected title=%s reason=untrusted_detail_source body_source=%s",
                item.title,
                detail.body_source,
            )
            state.mark_processed(item.dedupe_key)
            continue
        state.clear_detail_retry(item.dedupe_key)
        detail_text = detail.full_text
        detail_url = detail.url
        detail_time = detail.publish_time
        body_source = detail.body_source
        combined_text = join_nonempty([item.title, detail_text], "\n")
        result = match_announcement(
            combined_text,
            config.match_keywords_perpetual,
            config.match_keywords_delist,
            symbols,
            title=item.title,
        )
        logger.debug(
            "checked title=%s body_source=%s perpetual_hits=%s delist_hits=%s symbols=%s",
            item.title,
            body_source,
            result.perpetual_keywords,
            result.delist_keywords,
            result.symbols,
        )
        if not result.is_candidate:
            logger.info(
                "candidate rejected title=%s reason=keyword_mismatch body_source=%s",
                item.title,
                body_source,
            )
            state.mark_processed(item.dedupe_key)
            continue
        if not result.symbols:
            logger.info(
                "candidate rejected title=%s reason=no_supported_symbols body_source=%s",
                item.title,
                body_source,
            )
            state.mark_processed(item.dedupe_key)
            continue
        emit_signal(
            logger,
            item.title,
            detail_url,
            detail_time,
            result.perpetual_keywords + result.delist_keywords,
            result.symbols,
            summarize(detail_text),
        )
        trade_executor.handle_signal(
            announcement_id=item.dedupe_key,
            announcement_title=item.title,
            announcement_url=detail_url,
            announcement_publish_time=detail_time.isoformat(),
            matched_keywords=result.perpetual_keywords + result.delist_keywords,
            matched_symbols=result.symbols,
        )
        signals += 1
        state.mark_processed(item.dedupe_key)

    try:
        state.save()
    except Exception as exc:
        logger.warning("state save failed: %s", exc)

    if heartbeat.due(config.heartbeat_interval_seconds):
        logger.info("[HEARTBEAT] alive at %s", heartbeat.last_heartbeat.isoformat() if heartbeat.last_heartbeat else "startup")
        heartbeat.beat()

    trade_executor.monitor_positions_once()

    return signals


def run_testnet_smoke(config, logger: logging.Logger, symbol: str) -> int:
    if config.exchange_mode != "testnet":
        raise RuntimeError("testnet smoke mode requires EXCHANGE_MODE=testnet")
    if config.dry_run or not config.live_trading_enabled:
        raise RuntimeError("testnet smoke mode requires DRY_RUN=false and LIVE_TRADING_ENABLED=true")
    orchestrator = TradeOrchestrator(config)
    try:
        logger.info("testnet smoke started for %s", symbol)
        price = orchestrator.exchange.get_price(symbol)
        logger.info("testnet smoke price check symbol=%s price=%s", symbol, price)
        result = orchestrator.handle_signal(
            announcement_id="testnet-smoke",
            announcement_title=f"Testnet smoke {symbol}",
            announcement_url="https://example.invalid/testnet-smoke",
            announcement_publish_time="2026-04-14T00:00:00",
            matched_keywords=["perpetual", "delist"],
            matched_symbols=[symbol],
        )
        status = str(result.get("status", "unknown"))
        if status not in {"opened", "partial_opened"}:
            reason = result.get("reason") or result.get("error") or "unknown"
            raise RuntimeError(f"testnet smoke signal failed before open: status={status} reason={reason}")
        logger.info("testnet smoke opened signal_id=%s pool_id=%s", result.get("signal_id"), result.get("pool_id"))
        open_positions = result.get("positions", [])
        if not open_positions:
            raise RuntimeError(f"testnet smoke returned status={status} but did not open any positions")
        monitor_results = orchestrator.monitor_positions_once()
        logger.info("testnet smoke monitor results=%s", monitor_results)
        for pos in list(orchestrator.store.list_open_positions()):
            closed = orchestrator.engine.close_position(pos, orchestrator.exchange.get_price(pos["symbol"]), "smoke_test_close")
            orchestrator.lifecycle.mark_position_closed(closed.signal_id, close_pnl=float(closed.pnl))
            logger.info(
                "testnet smoke closed position_id=%s symbol=%s pnl=%s",
                closed.position_id,
                closed.symbol,
                closed.pnl,
            )
        orchestrator.monitor_positions_once()
        logger.info("testnet smoke completed")
        return 0
    finally:
        orchestrator.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Binance perpetual delist announcement monitor")
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    parser.add_argument("--testnet-smoke", action="store_true", help="run a controlled testnet trading smoke test")
    parser.add_argument("--smoke-symbol", default="BTCUSDT", help="symbol to use for the testnet smoke test")
    args = parser.parse_args()
    config = load_config()
    logger = setup_logging(config.log_file)
    validate_runtime_config(config)
    logger.info(
        "runtime ready mode=%s dry_run=%s live_trading_enabled=%s leverage=%s mock_seed_capital=%s max_active_signal_pools=%s",
        config.exchange_mode,
        config.dry_run,
        config.live_trading_enabled,
        config.leverage,
        config.total_capital,
        config.max_active_signal_pools,
    )
    state = StateStore(config.state_file)
    heartbeat = Heartbeat()
    trade_executor = TradeExecutor(config)
    logger.info("monitor started")
    try:
        if args.testnet_smoke:
            try:
                return run_testnet_smoke(config, logger, args.smoke_symbol.upper())
            except KeyboardInterrupt:
                logger.info("shutdown requested")
                return 0
            except Exception as exc:
                logger.exception("testnet smoke error: %s", exc)
                return 1
        if args.once:
            try:
                run_once(config, logger, state, heartbeat, trade_executor)
                return 0
            except KeyboardInterrupt:
                logger.info("shutdown requested")
                return 0
            except Exception as exc:
                logger.exception("main loop error: %s", exc)
                return 1
        while True:
            try:
                run_once(config, logger, state, heartbeat, trade_executor)
            except KeyboardInterrupt:
                logger.info("shutdown requested")
                return 0
            except Exception as exc:
                logger.exception("main loop error: %s", exc)
            time.sleep(config.poll_interval_seconds)
    finally:
        try:
            trade_executor.orchestrator.close()
        except Exception:
            pass
