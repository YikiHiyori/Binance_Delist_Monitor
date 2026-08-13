from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Protocol
from urllib.parse import urlencode

import requests

from .trade_models import AccountSnapshot


@dataclass
class ExchangeOrderResult:
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: float
    status: str
    created_at: str


@dataclass
class ExchangePosition:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    unrealized_pnl: float = 0.0
    mark_price: float = 0.0


@dataclass
class ExchangeIncome:
    symbol: str
    income_type: str
    income: float
    asset: str
    info: str
    time_ms: int
    transaction_id: str


class ExchangeClient(Protocol):
    def get_price(self, symbol: str) -> float:
        ...

    def get_account_snapshot(self) -> AccountSnapshot:
        ...

    def get_account_balance(self) -> float:
        ...

    def round_quantity(self, symbol: str, quantity: float) -> float:
        ...

    def place_short_order(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        ...

    def close_position(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        ...

    def get_position(self, symbol: str) -> Optional[ExchangePosition]:
        ...

    def list_positions(self) -> List[ExchangePosition]:
        ...

    def ensure_symbol_configuration(self, symbol: str, margin_type: str = "CROSSED", leverage: int = 1) -> Dict[str, object]:
        ...

    def is_symbol_tradable(self, symbol: str) -> bool:
        ...

    def get_exchange_info(self) -> Dict[str, object]:
        ...

    def get_symbol_delivery_time(self, symbol: str, force_refresh: bool = False) -> Optional[int]:
        ...

    def get_income_history(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        income_types: Optional[Iterable[str]] = None,
    ) -> List[ExchangeIncome]:
        ...


class MockExchangeClient:
    def __init__(
        self,
        price_map: Optional[Dict[str, Iterable[float]]] = None,
        default_price: float = 100.0,
        account_balance: float = 1000.0,
    ):
        self.default_price = float(default_price)
        self.account_snapshot = AccountSnapshot(
            available_balance=float(account_balance),
            total_margin_balance=float(account_balance),
            total_wallet_balance=float(account_balance),
            total_unrealized_profit=0.0,
            fetched_at=datetime.utcnow().isoformat(),
        )
        self.price_map: Dict[str, List[float]] = {}
        self.price_index: Dict[str, int] = {}
        self.positions: Dict[str, ExchangePosition] = {}
        self.orders: List[ExchangeOrderResult] = []
        self.symbol_configs: Dict[str, Dict[str, object]] = {}
        self.symbol_metadata: Dict[str, Dict[str, object]] = {}
        self.income_history: Dict[str, List[ExchangeIncome]] = {}
        if price_map:
            for symbol, seq in price_map.items():
                self.set_price_series(symbol, seq)

    def set_price_series(self, symbol: str, prices: Iterable[float]) -> None:
        upper = symbol.upper()
        self.price_map[upper] = [float(p) for p in prices]
        self.price_index[upper] = 0
        self.symbol_metadata.setdefault(upper, {"status": "TRADING", "deliveryDate": None})

    def set_price(self, symbol: str, price: float) -> None:
        upper = symbol.upper()
        self.price_map[upper] = [float(price)]
        self.price_index[upper] = 0
        self.symbol_metadata.setdefault(upper, {"status": "TRADING", "deliveryDate": None})

    def set_symbol_metadata(self, symbol: str, *, status: str = "TRADING", delivery_time_ms: Optional[int] = None) -> None:
        self.symbol_metadata[symbol.upper()] = {"status": str(status).upper(), "deliveryDate": delivery_time_ms}

    def append_income(
        self,
        symbol: str,
        income: float,
        *,
        income_type: str = "REALIZED_PNL",
        asset: str = "USDT",
        info: str = "",
        time_ms: Optional[int] = None,
        transaction_id: Optional[str] = None,
    ) -> None:
        upper = symbol.upper()
        records = self.income_history.setdefault(upper, [])
        next_time = int(time.time() * 1000) if time_ms is None else int(time_ms)
        next_tran_id = transaction_id or f"{upper}-{len(records)}"
        records.append(
            ExchangeIncome(
                symbol=upper,
                income_type=str(income_type),
                income=float(income),
                asset=str(asset),
                info=str(info),
                time_ms=next_time,
                transaction_id=str(next_tran_id),
            )
        )

    def get_price(self, symbol: str) -> float:
        symbol = symbol.upper()
        series = self.price_map.get(symbol)
        if not series:
            return self.default_price
        idx = self.price_index.get(symbol, 0)
        price = series[min(idx, len(series) - 1)]
        if idx < len(series) - 1:
            self.price_index[symbol] = idx + 1
        return float(price)

    def get_account_snapshot(self) -> AccountSnapshot:
        return self.account_snapshot

    def get_account_balance(self) -> float:
        return float(self.account_snapshot.strategy_total_capital)

    def set_account_snapshot(
        self,
        *,
        total_margin_balance: float,
        available_balance: Optional[float] = None,
        total_wallet_balance: Optional[float] = None,
        total_unrealized_profit: float = 0.0,
    ) -> None:
        balance = float(total_margin_balance)
        self.account_snapshot = AccountSnapshot(
            available_balance=float(available_balance if available_balance is not None else balance),
            total_margin_balance=balance,
            total_wallet_balance=float(total_wallet_balance if total_wallet_balance is not None else balance),
            total_unrealized_profit=float(total_unrealized_profit),
            fetched_at=datetime.utcnow().isoformat(),
        )

    def set_account_balance(self, balance: float) -> None:
        self.set_account_snapshot(total_margin_balance=float(balance), available_balance=float(balance))

    def round_quantity(self, symbol: str, quantity: float) -> float:
        return float(quantity)

    def place_short_order(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        symbol = symbol.upper()
        self.ensure_symbol_configuration(
            symbol,
            margin_type=str(kwargs.get("margin_type", "CROSSED")).upper(),
            leverage=int(kwargs.get("leverage", 1)),
        )
        order = ExchangeOrderResult(
            order_id=self._order_id("open", symbol, price, quantity),
            symbol=symbol,
            side="SHORT",
            price=float(price),
            quantity=float(quantity),
            status="FILLED",
            created_at=datetime.utcnow().isoformat(),
        )
        self.positions[symbol] = ExchangePosition(symbol=symbol, side="SHORT", quantity=float(quantity), entry_price=float(price))
        self.orders.append(order)
        return order

    def close_position(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        symbol = symbol.upper()
        order = ExchangeOrderResult(
            order_id=self._order_id("close", symbol, price, quantity),
            symbol=symbol,
            side="BUY",
            price=float(price),
            quantity=float(quantity),
            status="FILLED",
            created_at=datetime.utcnow().isoformat(),
        )
        self.positions.pop(symbol, None)
        self.orders.append(order)
        return order

    def get_position(self, symbol: str) -> Optional[ExchangePosition]:
        return next((position for position in self.list_positions() if position.symbol == symbol.upper() and position.side == "SHORT"), None)

    def list_positions(self) -> List[ExchangePosition]:
        snapshots: List[ExchangePosition] = []
        for symbol, position in list(self.positions.items()):
            mark_price = self.get_price(symbol)
            unrealized_pnl = (float(position.entry_price) - float(mark_price)) * float(position.quantity)
            snapshots.append(
                ExchangePosition(
                    symbol=symbol,
                    side=position.side,
                    quantity=float(position.quantity),
                    entry_price=float(position.entry_price),
                    unrealized_pnl=float(unrealized_pnl),
                    mark_price=float(mark_price),
                )
            )
        return snapshots

    def ensure_symbol_configuration(self, symbol: str, margin_type: str = "CROSSED", leverage: int = 1) -> Dict[str, object]:
        config = {"margin_type": margin_type.upper(), "leverage": int(leverage), "status": "mock"}
        self.symbol_configs[symbol.upper()] = config
        return config

    def is_symbol_tradable(self, symbol: str) -> bool:
        upper = symbol.upper()
        metadata = self.symbol_metadata.get(upper)
        if metadata is not None:
            return str(metadata.get("status", "")).upper() == "TRADING"
        return upper in self.price_map or upper in self.positions

    def get_exchange_info(self) -> Dict[str, object]:
        symbols = sorted(set(self.price_map.keys()) | set(self.positions.keys()) | set(self.symbol_metadata.keys()))
        return {
            "mode": "mock",
            "fapi": {
                "symbols": [
                    {
                        "symbol": symbol,
                        "status": self.symbol_metadata.get(symbol, {}).get("status", "TRADING"),
                        "deliveryDate": self.symbol_metadata.get(symbol, {}).get("deliveryDate"),
                    }
                    for symbol in symbols
                ]
            },
        }

    def get_symbol_delivery_time(self, symbol: str, force_refresh: bool = False) -> Optional[int]:
        metadata = self.symbol_metadata.get(symbol.upper(), {})
        value = metadata.get("deliveryDate")
        return int(value) if value is not None else None

    def get_income_history(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        income_types: Optional[Iterable[str]] = None,
    ) -> List[ExchangeIncome]:
        upper = symbol.upper()
        records = list(self.income_history.get(upper, []))
        allowed_types = {str(item).upper() for item in income_types} if income_types else None
        filtered: List[ExchangeIncome] = []
        for record in records:
            if start_time_ms is not None and record.time_ms < int(start_time_ms):
                continue
            if end_time_ms is not None and record.time_ms > int(end_time_ms):
                continue
            if allowed_types is not None and record.income_type.upper() not in allowed_types:
                continue
            filtered.append(record)
        return filtered

    def _order_id(self, prefix: str, symbol: str, price: float, quantity: float) -> str:
        raw = f"{prefix}:{symbol}:{price}:{quantity}:{len(self.orders)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class BinanceFuturesClient:
    """
    Thin REST client for Binance USD-M Futures.

    Safety rules:
    - testnet=True enables testnet REST endpoints.
    - all signed trading requests still require explicit live-trading config and credentials.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        live_trading_enabled: bool,
        dry_run: bool,
        testnet: bool = False,
        session: Optional[requests.Session] = None,
        timeout_seconds: int = 10,
        exchange_info_ttl_seconds: int = 300,
        account_snapshot_ttl_seconds: int = 2,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.live_trading_enabled = live_trading_enabled
        self.dry_run = dry_run
        self.testnet = testnet
        self.timeout_seconds = int(timeout_seconds)
        self.exchange_info_ttl_seconds = int(exchange_info_ttl_seconds)
        self.account_snapshot_ttl_seconds = int(account_snapshot_ttl_seconds)
        self.session = session or requests.Session()
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        self._quantity_rules: Dict[str, Dict[str, float]] = {}
        self._dual_side_mode: Optional[bool] = None
        self._exchange_info_cache: Optional[Dict[str, object]] = None
        self._exchange_info_cached_at: float = 0.0
        self._account_snapshot_cache: Optional[AccountSnapshot] = None
        self._account_snapshot_cached_at: float = 0.0
        self._configured_symbols: Dict[str, Dict[str, object]] = {}

    def _ensure_trading_allowed(self) -> None:
        if self.dry_run or not self.live_trading_enabled:
            raise PermissionError("Binance trading requires DRY_RUN=false and LIVE_TRADING_ENABLED=true")
        if not self.api_key or not self.api_secret:
            raise PermissionError("binance api credentials are required")

    def _ensure_signed_allowed(self) -> None:
        if self.dry_run or not self.live_trading_enabled:
            raise PermissionError("signed Binance requests require DRY_RUN=false and LIVE_TRADING_ENABLED=true")
        if not self.api_key or not self.api_secret:
            raise PermissionError("binance api credentials are required")

    def _sign_params(self, params: Dict[str, object]) -> Dict[str, object]:
        self._ensure_signed_allowed()
        payload = dict(params)
        payload["timestamp"] = int(time.time() * 1000)
        payload["recvWindow"] = 5000
        query = urlencode(payload, doseq=True)
        signature = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload

    def _request(self, method: str, path: str, params: Optional[Dict[str, object]] = None, signed: bool = False):
        payload = dict(params or {})
        headers = {}
        if signed:
            payload = self._sign_params(payload)
            headers["X-MBX-APIKEY"] = self.api_key
        elif self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        url = f"{self.base_url}{path}"
        request_kwargs = {"headers": headers, "timeout": self.timeout_seconds}
        if method.upper() == "GET":
            request_kwargs["params"] = payload
        else:
            request_kwargs["data"] = payload

        response = self.session.request(method.upper(), url, **request_kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                data = response.json()
            except Exception:
                raise exc
            if isinstance(data, dict) and "code" in data:
                raise RuntimeError(f"binance api error: {data}") from exc
            raise exc
        data = response.json()
        if isinstance(data, dict) and "code" in data and data.get("code") not in (0, 200, None):
            raise RuntimeError(f"binance api error: {data}")
        if not isinstance(data, (dict, list)):
            raise RuntimeError(f"unexpected binance response type: {type(data).__name__}")
        return data

    def _order_result(self, payload: Dict[str, object], symbol: str, side: str, fallback_price: float) -> ExchangeOrderResult:
        order_id = str(payload.get("orderId") or payload.get("clientOrderId") or self._fallback_order_id(symbol, fallback_price))
        price = self._parse_float(payload.get("avgPrice"), fallback_price)
        if price <= 0:
            price = self._parse_float(payload.get("price"), fallback_price)
        quantity = self._parse_float(payload.get("executedQty"), 0.0)
        if quantity <= 0:
            quantity = self._parse_float(payload.get("origQty"), 0.0)
        status = str(payload.get("status") or "FILLED")
        return ExchangeOrderResult(
            order_id=order_id,
            symbol=symbol.upper(),
            side=side,
            price=price if price > 0 else float(fallback_price),
            quantity=quantity if quantity > 0 else float(payload.get("origQty") or 0.0),
            status=status,
            created_at=datetime.utcnow().isoformat(),
        )

    def _fallback_order_id(self, symbol: str, price: float) -> str:
        raw = f"{symbol}:{price}:{time.time_ns()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _parse_float(value: object, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _round_down_to_step(value: float, step: float) -> float:
        if value <= 0:
            return 0.0
        if step <= 0:
            return float(value)
        value_dec = Decimal(str(value))
        step_dec = Decimal(str(step))
        rounded = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
        return float(rounded)

    def _exchange_info_payload(self, force_refresh: bool = False) -> Dict[str, object]:
        now = time.time()
        if (
            not force_refresh
            and self._exchange_info_cache is not None
            and now - self._exchange_info_cached_at < self.exchange_info_ttl_seconds
        ):
            return self._exchange_info_cache
        payload = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected exchange info response type: {type(payload).__name__}")
        self._exchange_info_cache = payload
        self._exchange_info_cached_at = now
        return payload

    def _find_symbol_info(self, symbol: str, force_refresh: bool = False) -> Optional[Dict[str, object]]:
        upper = symbol.upper()
        payload = self._exchange_info_payload(force_refresh=force_refresh)
        for item in payload.get("symbols", []):
            if str(item.get("symbol", "")).upper() == upper:
                return item if isinstance(item, dict) else None
        return None

    def _get_quantity_rules(self, symbol: str) -> Dict[str, float]:
        symbol = symbol.upper()
        cached = self._quantity_rules.get(symbol)
        if cached is not None:
            return cached
        payload = self._exchange_info_payload()
        rules = {"step_size": 0.0, "min_qty": 0.0}
        for item in payload.get("symbols", []):
            if str(item.get("symbol", "")).upper() != symbol:
                continue
            filters: Dict[str, Dict[str, object]] = {}
            for filter_item in item.get("filters", []):
                if isinstance(filter_item, dict) and filter_item.get("filterType"):
                    filters[str(filter_item["filterType"])] = filter_item
            quantity_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            rules["step_size"] = self._parse_float(quantity_filter.get("stepSize"), 0.0)
            rules["min_qty"] = self._parse_float(quantity_filter.get("minQty"), 0.0)
            break
        self._quantity_rules[symbol] = rules
        return rules

    def _is_dual_side_mode(self) -> bool:
        if self._dual_side_mode is not None:
            return self._dual_side_mode
        payload = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        enabled = payload.get("dualSidePosition")
        if isinstance(enabled, bool):
            self._dual_side_mode = enabled
        else:
            self._dual_side_mode = str(enabled).strip().lower() == "true"
        return self._dual_side_mode

    def round_quantity(self, symbol: str, quantity: float) -> float:
        rules = self._get_quantity_rules(symbol)
        rounded = self._round_down_to_step(quantity, rules["step_size"])
        if rules["min_qty"] > 0 and rounded < rules["min_qty"]:
            return 0.0
        return rounded

    def get_price(self, symbol: str) -> float:
        data = self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol.upper()}, signed=False)
        return self._parse_float(data.get("price"), 0.0)

    def get_account_snapshot(self) -> AccountSnapshot:
        now = time.time()
        if self._account_snapshot_cache is not None and now - self._account_snapshot_cached_at < self.account_snapshot_ttl_seconds:
            return self._account_snapshot_cache
        data = self._request("GET", "/fapi/v3/account", signed=True)
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected account response type: {type(data).__name__}")
        snapshot = AccountSnapshot(
            available_balance=self._parse_float(data.get("availableBalance"), 0.0),
            total_margin_balance=self._parse_float(data.get("totalMarginBalance"), 0.0),
            total_wallet_balance=self._parse_float(data.get("totalWalletBalance"), 0.0),
            total_unrealized_profit=self._parse_float(data.get("totalUnrealizedProfit"), 0.0),
            fetched_at=datetime.utcnow().isoformat(),
        )
        self._account_snapshot_cache = snapshot
        self._account_snapshot_cached_at = now
        return snapshot

    def get_account_balance(self) -> float:
        return float(self.get_account_snapshot().strategy_total_capital)

    def _ensure_margin_type(self, symbol: str, margin_type: str) -> str:
        try:
            self._request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}, signed=True)
            return "updated"
        except RuntimeError as exc:
            message = str(exc)
            if "-4046" in message or "No need to change margin type" in message:
                return "already_set"
            raise

    def _ensure_leverage(self, symbol: str, leverage: int) -> Dict[str, object]:
        response = self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)}, signed=True)
        if not isinstance(response, dict):
            raise RuntimeError(f"unexpected leverage response type: {type(response).__name__}")
        return response

    def ensure_symbol_configuration(self, symbol: str, margin_type: str = "CROSSED", leverage: int = 1) -> Dict[str, object]:
        self._ensure_trading_allowed()
        symbol = symbol.upper()
        target = {"margin_type": margin_type.upper(), "leverage": int(leverage)}
        cached = self._configured_symbols.get(symbol)
        if cached == target:
            return {**target, "status": "cached"}
        margin_status = self._ensure_margin_type(symbol, target["margin_type"])
        leverage_response = self._ensure_leverage(symbol, target["leverage"])
        self._configured_symbols[symbol] = dict(target)
        return {
            **target,
            "status": "updated",
            "margin_status": margin_status,
            "exchange_leverage": int(leverage_response.get("leverage") or target["leverage"]),
        }

    def place_short_order(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        symbol = symbol.upper()
        self._ensure_trading_allowed()
        self.ensure_symbol_configuration(
            symbol,
            margin_type=str(kwargs.get("margin_type", "CROSSED")).upper(),
            leverage=int(kwargs.get("leverage", 1)),
        )
        quantity = self.round_quantity(symbol, quantity)
        if quantity <= 0:
            raise ValueError(f"quantity for {symbol} is below Binance minimum after rounding")
        payload = {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity,
            "newOrderRespType": "RESULT",
        }
        if self._is_dual_side_mode():
            payload["positionSide"] = "SHORT"
        data = self._request("POST", "/fapi/v1/order", payload, signed=True)
        return self._order_result(data, symbol, "SHORT", price)

    def close_position(self, symbol: str, quantity: float, price: float, **kwargs) -> ExchangeOrderResult:
        symbol = symbol.upper()
        self._ensure_trading_allowed()
        quantity = self.round_quantity(symbol, quantity)
        if quantity <= 0:
            raise ValueError(f"quantity for {symbol} is below Binance minimum after rounding")
        payload = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        }
        if self._is_dual_side_mode():
            payload["positionSide"] = "SHORT"
        data = self._request("POST", "/fapi/v1/order", payload, signed=True)
        return self._order_result(data, symbol, "BUY", price)

    def list_positions(self) -> List[ExchangePosition]:
        self._ensure_signed_allowed()
        data = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected position response type: {type(data).__name__}")
        positions: List[ExchangePosition] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            position_amt = self._parse_float(row.get("positionAmt"), 0.0)
            if position_amt == 0:
                continue
            side = "SHORT" if position_amt < 0 else "LONG"
            positions.append(
                ExchangePosition(
                    symbol=str(row.get("symbol", "")).upper(),
                    side=side,
                    quantity=abs(position_amt),
                    entry_price=self._parse_float(row.get("entryPrice"), 0.0),
                    unrealized_pnl=self._parse_float(row.get("unRealizedProfit"), 0.0),
                    mark_price=self._parse_float(row.get("markPrice"), 0.0),
                )
            )
        return positions

    def get_position(self, symbol: str) -> Optional[ExchangePosition]:
        symbol = symbol.upper()
        positions = [position for position in self.list_positions() if position.symbol == symbol and position.side == "SHORT"]
        return positions[0] if positions else None

    def is_symbol_tradable(self, symbol: str) -> bool:
        item = self._find_symbol_info(symbol)
        if item is not None:
            return str(item.get("status", "")).upper() == "TRADING"
        return False

    def get_exchange_info(self) -> Dict[str, object]:
        return {"mode": "testnet" if self.testnet else "live", "fapi": self._exchange_info_payload()}

    def get_symbol_delivery_time(self, symbol: str, force_refresh: bool = False) -> Optional[int]:
        item = self._find_symbol_info(symbol, force_refresh=force_refresh)
        if item is None:
            return None
        value = item.get("deliveryDate")
        if value in (None, ""):
            return None
        try:
            return int(value)
        except Exception:
            return None

    def get_income_history(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        income_types: Optional[Iterable[str]] = None,
    ) -> List[ExchangeIncome]:
        self._ensure_signed_allowed()
        params: Dict[str, object] = {"symbol": symbol.upper(), "limit": 1000}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        data = self._request("GET", "/fapi/v1/income", params, signed=True)
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected income history response type: {type(data).__name__}")
        allowed_types = {str(item).upper() for item in income_types} if income_types else None
        records: List[ExchangeIncome] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            income_type = str(row.get("incomeType", ""))
            if allowed_types is not None and income_type.upper() not in allowed_types:
                continue
            row_symbol = str(row.get("symbol", symbol)).upper()
            if row_symbol != symbol.upper():
                continue
            records.append(
                ExchangeIncome(
                    symbol=row_symbol,
                    income_type=income_type,
                    income=self._parse_float(row.get("income"), 0.0),
                    asset=str(row.get("asset", "")),
                    info=str(row.get("info", "")),
                    time_ms=int(self._parse_float(row.get("time"), 0.0)),
                    transaction_id=str(row.get("tranId", "")),
                )
            )
        records.sort(key=lambda item: item.time_ms)
        return records
