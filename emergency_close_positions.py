from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from binance_delist_monitor.runner import validate_runtime_config  # noqa: E402
from binance_delist_monitor.trade_orchestrator import TradeOrchestrator  # noqa: E402
from binance_delist_monitor.trade_models import iso_to_timestamp_ms, timestamp_ms_to_iso  # noqa: E402


POSITION_CLOSE_INCOME_TYPES = {"REALIZED_PNL", "COMMISSION"}
REPORT_PREFIX = "emergency_close_report"


def _utc_now() -> datetime:
    return datetime.utcnow()


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _income_to_dict(record) -> Dict[str, object]:
    return {
        "symbol": record.symbol,
        "income_type": record.income_type,
        "income": float(record.income),
        "asset": record.asset,
        "info": record.info,
        "time_ms": int(record.time_ms),
        "time_iso": timestamp_ms_to_iso(int(record.time_ms)),
        "transaction_id": record.transaction_id,
    }


def _summarize_income(records: Iterable[object]) -> Dict[str, object]:
    by_type: Dict[str, float] = defaultdict(float)
    by_asset: Dict[str, float] = defaultdict(float)
    total = 0.0
    for record in records:
        value = float(record.income)
        total += value
        by_type[str(record.income_type)] += value
        by_asset[str(record.asset)] += value
    return {
        "total": total,
        "by_type": dict(sorted(by_type.items())),
        "by_asset": dict(sorted(by_asset.items())),
    }


def _snapshot_to_dict(snapshot) -> Dict[str, object]:
    return {
        "available_balance": float(snapshot.available_balance),
        "total_margin_balance": float(snapshot.total_margin_balance),
        "total_wallet_balance": float(snapshot.total_wallet_balance),
        "total_unrealized_profit": float(snapshot.total_unrealized_profit),
        "capital_basis": snapshot.capital_basis,
        "strategy_total_capital": float(snapshot.strategy_total_capital),
        "fetched_at": snapshot.fetched_at,
    }


def _refresh_account_snapshot(exchange, settle_wait_seconds: float = 3.0):
    time.sleep(max(0.0, settle_wait_seconds))
    if hasattr(exchange, "_account_snapshot_cache"):
        exchange._account_snapshot_cache = None
    if hasattr(exchange, "_account_snapshot_cached_at"):
        exchange._account_snapshot_cached_at = 0.0
    return exchange.get_account_snapshot()


def _wait_for_exchange_close(exchange, symbol: str, attempts: int = 10, interval_seconds: float = 1.0) -> bool:
    for _ in range(max(1, attempts)):
        position = exchange.get_position(symbol)
        if position is None or _float(position.quantity) <= 0:
            return True
        time.sleep(interval_seconds)
    return False


def _has_recent_close_income(records: Iterable[object], close_submit_ms: int) -> bool:
    threshold = int(close_submit_ms) - 10000
    for record in records:
        if int(record.time_ms) < threshold:
            continue
        if str(record.income_type).upper() in POSITION_CLOSE_INCOME_TYPES:
            return True
    return False


def _wait_for_income_history(
    exchange,
    symbol: str,
    start_time_ms: int | None,
    close_submit_ms: int,
    max_wait_seconds: int = 30,
    poll_interval_seconds: float = 2.0,
) -> List[object]:
    deadline = time.time() + max(1, max_wait_seconds)
    last_records: List[object] = []
    while True:
        last_records = exchange.get_income_history(
            symbol,
            start_time_ms=start_time_ms,
            end_time_ms=int(time.time() * 1000) + 1000,
        )
        if _has_recent_close_income(last_records, close_submit_ms):
            return last_records
        if time.time() >= deadline:
            return last_records
        time.sleep(poll_interval_seconds)


def _close_position(orchestrator: TradeOrchestrator, position: Dict[str, object]) -> Dict[str, object]:
    exchange = orchestrator.exchange
    symbol = str(position["symbol"]).upper()
    exchange_position = exchange.get_position(symbol)
    if exchange_position is None or _float(exchange_position.quantity) <= 0:
        return {
            "position_id": position["position_id"],
            "signal_id": position["signal_id"],
            "symbol": symbol,
            "status": "already_closed_on_exchange",
            "message": "No active short position found on exchange.",
        }

    close_reference_price = _float(exchange_position.mark_price)
    if close_reference_price <= 0:
        close_reference_price = _float(exchange.get_price(symbol))
    quantity = _float(exchange_position.quantity)
    open_time_ms = iso_to_timestamp_ms(str(position["open_time"]))
    income_start_ms = max(0, int(open_time_ms) - 60000) if open_time_ms is not None else None

    orchestrator.logger.emit(
        "emergency_close_submit_request",
        submit_time=_utc_now().isoformat(),
        position_id=position["position_id"],
        signal_id=position["signal_id"],
        symbol=symbol,
        quantity=quantity,
        side="BUY",
        order_type="MARKET",
        reduce_only=True,
        close_reason="emergency_manual_close",
        exchange_mode=orchestrator.config.exchange_mode,
    )

    close_order = exchange.close_position(symbol, quantity, close_reference_price)
    close_submit_ms = int(time.time() * 1000)
    close_verified = _wait_for_exchange_close(exchange, symbol)
    income_records = _wait_for_income_history(exchange, symbol, income_start_ms, close_submit_ms)
    income_summary = _summarize_income(income_records)
    realized_pnl = income_summary["total"] if income_records else None
    close_time_iso = timestamp_ms_to_iso(max((record.time_ms for record in income_records), default=close_submit_ms)) or _utc_now().isoformat()
    gross_pnl = (_float(position["entry_price"]) - _float(close_order.price)) * quantity

    position_for_store = dict(position)
    position_for_store["quantity"] = quantity
    closed_record = orchestrator.engine.close_position(
        position_for_store,
        _float(close_order.price),
        "emergency_manual_close",
        execute_on_exchange=False,
        realized_pnl=realized_pnl,
        close_time=close_time_iso,
    )
    orchestrator.lifecycle.mark_position_closed(position["signal_id"], close_pnl=float(closed_record.pnl))

    orchestrator.logger.emit(
        "emergency_position_closed",
        close_time=closed_record.close_time,
        position_id=closed_record.position_id,
        signal_id=closed_record.signal_id,
        symbol=closed_record.symbol,
        close_order_id=close_order.order_id,
        close_price=closed_record.close_price,
        quantity=closed_record.quantity,
        realized_pnl=closed_record.pnl,
        realized_pnl_pct=closed_record.pnl_pct,
        gross_pnl_estimate=gross_pnl,
        income_record_count=len(income_records),
        close_verified=close_verified,
    )

    return {
        "position_id": position["position_id"],
        "signal_id": position["signal_id"],
        "announcement_id": position["announcement_id"],
        "announcement_title": position["announcement_title"],
        "announcement_url": position["announcement_url"],
        "symbol": symbol,
        "status": "closed",
        "close_verified": close_verified,
        "local_position": {
            "entry_price": _float(position["entry_price"]),
            "open_time": position["open_time"],
            "allocated_capital": _float(position["allocated_capital"]),
            "quantity": quantity,
            "pool_id": position["pool_id"],
            "trade_id": position["trade_id"],
        },
        "close_order": asdict(close_order),
        "gross_pnl_estimate": gross_pnl,
        "net_realized_pnl": float(closed_record.pnl),
        "net_realized_pnl_pct": float(closed_record.pnl_pct),
        "income_summary": income_summary,
        "income_records": [_income_to_dict(record) for record in income_records],
        "db_close_record": {
            "status": closed_record.status,
            "close_time": closed_record.close_time,
            "close_price": closed_record.close_price,
            "close_reason": closed_record.close_reason,
            "pnl": closed_record.pnl,
            "pnl_pct": closed_record.pnl_pct,
        },
    }


def _update_signal_statuses(orchestrator: TradeOrchestrator, signal_ids: Iterable[str]) -> None:
    for signal_id in sorted(set(str(item) for item in signal_ids if item)):
        open_positions = orchestrator.store.list_open_positions_by_signal(signal_id)
        status = "closed_manual" if not open_positions else "partial_closed_manual"
        orchestrator.store.update_signal(signal_id, status=status)


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(path: Path, payload: Dict[str, object]) -> None:
    lines: List[str] = []
    lines.append("# Emergency Close Report")
    lines.append("")
    lines.append(f"- Generated at: `{payload['generated_at']}`")
    lines.append(f"- Exchange mode: `{payload['exchange_mode']}`")
    lines.append(f"- Closed count: `{payload['summary']['closed_count']}`")
    lines.append(f"- Failed count: `{payload['summary']['failed_count']}`")
    lines.append(f"- Remaining open positions in DB: `{payload['summary']['remaining_db_open_positions']}`")
    lines.append(f"- Remaining exchange short positions: `{payload['summary']['remaining_exchange_short_positions']}`")
    lines.append("")
    lines.append("## Account")
    lines.append("")
    lines.append("### Before")
    for key, value in payload["account_before"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("### After")
    for key, value in payload["account_after"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Positions")
    lines.append("")
    for item in payload["positions"]:
        lines.append(f"### {item['symbol']}")
        lines.append(f"- Status: `{item['status']}`")
        if item["status"] != "closed":
            lines.append(f"- Message: `{item.get('message', '')}`")
            lines.append("")
            continue
        lines.append(f"- Signal ID: `{item['signal_id']}`")
        lines.append(f"- Announcement: `{item['announcement_title']}`")
        lines.append(f"- Entry price: `{item['local_position']['entry_price']}`")
        lines.append(f"- Entry quantity: `{item['local_position']['quantity']}`")
        lines.append(f"- Entry time: `{item['local_position']['open_time']}`")
        lines.append(f"- Close order id: `{item['close_order']['order_id']}`")
        lines.append(f"- Close price: `{item['close_order']['price']}`")
        lines.append(f"- Close quantity: `{item['close_order']['quantity']}`")
        lines.append(f"- Close time: `{item['db_close_record']['close_time']}`")
        lines.append(f"- Gross PnL estimate: `{item['gross_pnl_estimate']}`")
        lines.append(f"- Net realized PnL: `{item['net_realized_pnl']}`")
        lines.append(f"- Net realized PnL pct: `{item['net_realized_pnl_pct']}`")
        lines.append(f"- Income summary by type: `{json.dumps(item['income_summary']['by_type'], ensure_ascii=False)}`")
        lines.append("")
        if item["income_records"]:
            lines.append("Income records:")
            for record in item["income_records"]:
                lines.append(
                    f"- `{record['time_iso']}` `{record['income_type']}` `{record['income']}` `{record['asset']}` tx=`{record['transaction_id']}` info=`{record['info']}`"
                )
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    from binance_delist_monitor.config import load_config

    config = load_config()
    validate_runtime_config(config)
    if config.exchange_mode not in {"live", "testnet"}:
        raise RuntimeError(f"emergency close requires EXCHANGE_MODE=live or testnet; current={config.exchange_mode!r}")
    if config.dry_run or not config.live_trading_enabled:
        raise RuntimeError("emergency close requires DRY_RUN=false and LIVE_TRADING_ENABLED=true")

    orchestrator = TradeOrchestrator(config)
    report_time = _utc_now().isoformat()
    report_base = ROOT / "state" / f"{REPORT_PREFIX}_{_utc_stamp()}"
    try:
        db_open_positions = orchestrator.store.list_open_positions()
        account_before = _snapshot_to_dict(orchestrator.exchange.get_account_snapshot())
        orchestrator.logger.emit(
            "emergency_close_started",
            started_at=report_time,
            db_open_positions=len(db_open_positions),
            account_before=account_before,
            exchange_mode=config.exchange_mode,
        )

        results: List[Dict[str, object]] = []
        affected_signal_ids: List[str] = []
        for position in db_open_positions:
            affected_signal_ids.append(str(position["signal_id"]))
            try:
                results.append(_close_position(orchestrator, position))
            except Exception as exc:
                orchestrator.logger.emit(
                    "emergency_close_failed",
                    failed_at=_utc_now().isoformat(),
                    position_id=position["position_id"],
                    signal_id=position["signal_id"],
                    symbol=position["symbol"],
                    error=str(exc),
                )
                results.append(
                    {
                        "position_id": position["position_id"],
                        "signal_id": position["signal_id"],
                        "announcement_id": position["announcement_id"],
                        "announcement_title": position["announcement_title"],
                        "announcement_url": position["announcement_url"],
                        "symbol": position["symbol"],
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        _update_signal_statuses(orchestrator, affected_signal_ids)

        remaining_db_open_positions = orchestrator.store.list_open_positions()
        remaining_exchange_positions = [
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "quantity": float(pos.quantity),
                "entry_price": float(pos.entry_price),
                "unrealized_pnl": float(pos.unrealized_pnl),
                "mark_price": float(pos.mark_price),
            }
            for pos in orchestrator.exchange.list_positions()
            if str(pos.side).upper() == "SHORT" and _float(pos.quantity) > 0
        ]
        account_after = _snapshot_to_dict(_refresh_account_snapshot(orchestrator.exchange))
        summary = {
            "closed_count": sum(1 for item in results if item["status"] == "closed"),
            "failed_count": sum(1 for item in results if item["status"] == "failed"),
            "already_closed_count": sum(1 for item in results if item["status"] == "already_closed_on_exchange"),
            "remaining_db_open_positions": len(remaining_db_open_positions),
            "remaining_exchange_short_positions": len(remaining_exchange_positions),
            "net_realized_pnl_total": sum(_float(item.get("net_realized_pnl")) for item in results if item["status"] == "closed"),
            "gross_pnl_estimate_total": sum(_float(item.get("gross_pnl_estimate")) for item in results if item["status"] == "closed"),
        }
        report = {
            "generated_at": report_time,
            "exchange_mode": config.exchange_mode,
            "account_before": account_before,
            "account_after": account_after,
            "summary": summary,
            "positions": results,
            "remaining_db_open_positions": remaining_db_open_positions,
            "remaining_exchange_short_positions": remaining_exchange_positions,
        }
        json_path = report_base.with_suffix(".json")
        md_path = report_base.with_suffix(".md")
        _write_json(json_path, report)
        _write_markdown(md_path, report)
        orchestrator.logger.emit(
            "emergency_close_completed",
            completed_at=_utc_now().isoformat(),
            summary=summary,
            json_report=str(json_path),
            markdown_report=str(md_path),
        )
        print(json.dumps({"json_report": str(json_path), "markdown_report": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))
        return 0 if summary["failed_count"] == 0 and summary["remaining_exchange_short_positions"] == 0 else 1
    finally:
        orchestrator.close()


if __name__ == "__main__":
    raise SystemExit(main())
