from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence, Set

from .http_client import HttpClient

SUPPORTED_USDS_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP")
_SUPPORTED_PERPETUAL_SYMBOL_RE = re.compile(
    rf"^[A-Z0-9]{{2,}}(?:{'|'.join(SUPPORTED_USDS_QUOTES)})$"
)


@dataclass
class ContractCache:
    fetched_at: Optional[str]
    symbols: List[str]

    def is_fresh(self, ttl_seconds: int) -> bool:
        if not self.fetched_at:
            return False
        try:
            fetched = datetime.fromisoformat(self.fetched_at)
        except Exception:
            return False
        age = (datetime.utcnow() - fetched).total_seconds()
        return age < ttl_seconds


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def is_supported_perpetual_symbol(symbol: str) -> bool:
    return bool(_SUPPORTED_PERPETUAL_SYMBOL_RE.fullmatch(normalize_symbol(symbol)))


def sanitize_contract_symbols(symbols: Sequence[str]) -> List[str]:
    dedup: List[str] = []
    seen: Set[str] = set()
    for raw_symbol in symbols:
        symbol = normalize_symbol(raw_symbol)
        if not is_supported_perpetual_symbol(symbol):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        dedup.append(symbol)
    return dedup


class ContractUniverse:
    def __init__(self, http: HttpClient, futures_url: str = ""):
        self.http = http
        self.futures_url = futures_url

    def fetch_symbols(self) -> List[str]:
        symbols: List[str] = []
        if self.futures_url:
            try:
                payload = self.http.get_json(self.futures_url)
                for item in payload.get("symbols", []):
                    symbol = normalize_symbol(item.get("symbol", ""))
                    contract_type = str(item.get("contractType", "")).strip().upper()
                    if contract_type != "PERPETUAL":
                        continue
                    symbols.append(symbol)
            except Exception:
                pass
        return sanitize_contract_symbols(symbols)
