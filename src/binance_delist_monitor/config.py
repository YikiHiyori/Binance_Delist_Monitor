from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _split_csv(value: str) -> List[str]:
    items = []
    for part in value.replace("\n", ",").split(","):
        item = part.strip()
        if item:
            items.append(item)
    return items


def _parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass
class AppConfig:
    binance_api_key: str = ""
    binance_api_secret: str = ""
    heartbeat_webhook: str = ""
    alert_webhook: str = ""
    poll_interval_seconds: int = 30
    heartbeat_interval_seconds: int = 60
    match_keywords_perpetual: List[str] = field(
        default_factory=lambda: [
            "perpetual contract",
            "perpetual",
            "futures",
            "usd-m",
        ]
    )
    match_keywords_delist: List[str] = field(
        default_factory=lambda: [
            "delist",
            "will delist",
            "remove",
            "removed",
            "cease support",
        ]
    )
    default_short_usd_amount: float = 100.0
    contract_cache_ttl_seconds: int = 300
    dry_run: bool = True
    live_trading_enabled: bool = False
    take_profit_pct: float = 0.45
    stop_loss_pct: float = 0.08
    enable_take_profit: bool = True
    enable_stop_loss: bool = False
    total_capital: float = 1000.0
    leverage: int = 1
    max_active_signal_pools: int = 2
    price_poll_interval_seconds: int = 5
    allow_signal_queue: bool = False
    exchange_mode: str = "mock"
    trading_db_file: Path = field(default_factory=lambda: _project_root() / "state" / "trading.sqlite3")
    announcement_page_size: int = 20
    announcement_max_pages: int = 3
    state_file: Path = field(default_factory=lambda: _project_root() / "state" / "state.json")
    log_file: Path = field(default_factory=lambda: _project_root() / "logs" / "monitor.log")
    http_timeout_seconds: int = 20
    verify_ssl: bool = False
    official_list_url: str = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    futures_exchange_info_url: str = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    mirror_latest_url: str = "https://cache.bwe-ws.com/bn-latest"
    mirror_article_url_template: str = "https://cache.bwe-ws.com/bn-{article_id}"


def load_config() -> AppConfig:
    root = _project_root()
    candidates = [
        root / ".env",
        Path.cwd() / ".env",
        root.parent / ".env",
    ]
    for path in candidates:
        load_dotenv(path)
    return AppConfig(
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        heartbeat_webhook=os.getenv("HEARTBEAT_WEBHOOK", ""),
        alert_webhook=os.getenv("ALERT_WEBHOOK", ""),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "30")),
        heartbeat_interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60")),
        default_short_usd_amount=float(os.getenv("DEFAULT_SHORT_USD_AMOUNT", "100")),
        contract_cache_ttl_seconds=int(os.getenv("CONTRACT_CACHE_TTL_SECONDS", "300")),
        dry_run=_parse_bool(os.getenv("DRY_RUN", "true"), True),
        live_trading_enabled=_parse_bool(os.getenv("LIVE_TRADING_ENABLED", "false"), False),
        take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "0.15")),
        stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "0.08")),
        enable_take_profit=_parse_bool(os.getenv("ENABLE_TAKE_PROFIT", "true"), True),
        enable_stop_loss=_parse_bool(os.getenv("ENABLE_STOP_LOSS", "false"), False),
        total_capital=float(os.getenv("TOTAL_CAPITAL", "1000")),
        leverage=int(os.getenv("LEVERAGE", "1")),
        max_active_signal_pools=int(os.getenv("MAX_ACTIVE_SIGNAL_POOLS", "2")),
        price_poll_interval_seconds=int(os.getenv("PRICE_POLL_INTERVAL_SECONDS", "5")),
        allow_signal_queue=_parse_bool(os.getenv("ALLOW_SIGNAL_QUEUE", "false"), False),
        exchange_mode=os.getenv("EXCHANGE_MODE", "mock").strip().lower() or "mock",
        trading_db_file=Path(os.getenv("TRADING_DB_FILE", str(root / "state" / "trading.sqlite3"))),
        announcement_page_size=int(os.getenv("ANNOUNCEMENT_PAGE_SIZE", "20")),
        announcement_max_pages=int(os.getenv("ANNOUNCEMENT_MAX_PAGES", "3")),
        state_file=Path(os.getenv("STATE_FILE", str(root / "state" / "state.json"))),
        log_file=Path(os.getenv("LOG_FILE", str(root / "logs" / "monitor.log"))),
        match_keywords_perpetual=_split_csv(
            os.getenv(
                "MATCH_KEYWORDS_PERPETUAL",
                "perpetual contract,perpetual,futures,usd-m",
            )
        ),
        match_keywords_delist=_split_csv(
            os.getenv(
                "MATCH_KEYWORDS_DELIST",
                "delist,will delist,remove,removed,cease support",
            )
        ),
    )
