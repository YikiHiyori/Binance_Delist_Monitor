from __future__ import annotations

import re
from typing import List, Sequence

from .contracts import is_supported_perpetual_symbol, sanitize_contract_symbols
from .models import MatchResult
from .utils import compact_text, normalize_unicode_text, tokenized_upper_text, unique_preserve_order

_SUPPORTED_TITLE_MARKERS = ("BINANCE FUTURES", "WILL DELIST", "PERPETUAL CONTRACT")
_SUPPORTED_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP")
_SYMBOL_TOKEN_RE = re.compile(
    rf"\b([A-Z0-9]{{2,}})\s*(?:/|\s|-)?\s*({'|'.join(_SUPPORTED_QUOTES)})\b"
)
_EXPLICIT_SYMBOL_PATTERNS = (
    re.compile(r"BINANCE FUTURES\s+WILL DELIST\s+(.{0,220}?)\s+PERPETUAL CONTRACTS?", flags=re.I),
    re.compile(r"(?:WILL DELIST|DELIST)\s+(.{0,220}?)\s+PERPETUAL CONTRACTS?", flags=re.I),
    re.compile(r"(?:USD-M|USDS-M|USD S-M)\s+(.{0,220}?)\s+PERPETUAL CONTRACTS?", flags=re.I),
)


def detect_keywords(text: str, perpetual_keywords: Sequence[str], delist_keywords: Sequence[str]) -> MatchResult:
    normalized = tokenized_upper_text(text)
    compact = compact_text(text)
    perpetual_hits = []
    delist_hits = []
    for keyword in perpetual_keywords:
        k = keyword.strip()
        if not k:
            continue
        k_norm = tokenized_upper_text(k)
        k_compact = compact_text(k)
        if k_norm and k_norm in normalized:
            perpetual_hits.append(keyword)
        elif k_compact and k_compact in compact:
            perpetual_hits.append(keyword)
    for keyword in delist_keywords:
        k = keyword.strip()
        if not k:
            continue
        k_norm = tokenized_upper_text(k)
        k_compact = compact_text(k)
        if k_norm and k_norm in normalized:
            delist_hits.append(keyword)
        elif k_compact and k_compact in compact:
            delist_hits.append(keyword)
    return MatchResult(
        perpetual_keywords=unique_preserve_order(perpetual_hits),
        delist_keywords=unique_preserve_order(delist_hits),
        symbols=[],
    )


def looks_like_supported_futures_delist_title(title: str) -> bool:
    normalized = tokenized_upper_text(title)
    return all(marker in normalized for marker in _SUPPORTED_TITLE_MARKERS)


def _normalize_announcement_text(text: str) -> str:
    value = normalize_unicode_text(text).upper()
    return re.sub(r"\s+", " ", value)


def _extract_symbols_from_clause(clause: str) -> List[str]:
    matches: List[str] = []
    for base, quote in _SYMBOL_TOKEN_RE.findall(clause):
        symbol = f"{base}{quote}"
        if is_supported_perpetual_symbol(symbol):
            matches.append(symbol)
    return unique_preserve_order(matches)


def extract_explicit_symbols(text: str) -> List[str]:
    """
    Extract contract symbols that are explicitly listed in announcement prose.

    This targets patterns like:
    - USDⓈ-M OLUSDT, HIPPOUSDT, RLSUSDT and PUFFERUSDT Perpetual Contracts
    """
    normalized = _normalize_announcement_text(text)
    matches: List[str] = []
    for pattern in _EXPLICIT_SYMBOL_PATTERNS:
        for match in pattern.finditer(normalized):
            matches.extend(_extract_symbols_from_clause(match.group(1)))
    return unique_preserve_order(matches)


def match_symbols(text: str, symbols: Sequence[str]) -> List[str]:
    universe = set(sanitize_contract_symbols(symbols))
    explicit = extract_explicit_symbols(text)
    return [symbol for symbol in explicit if symbol in universe]


def match_announcement(
    text: str,
    perpetual_keywords: Sequence[str],
    delist_keywords: Sequence[str],
    symbols: Sequence[str],
    *,
    title: str | None = None,
) -> MatchResult:
    if title is not None and not looks_like_supported_futures_delist_title(title):
        return MatchResult(perpetual_keywords=[], delist_keywords=[], symbols=[])
    keyword_result = detect_keywords(text, perpetual_keywords, delist_keywords)
    symbol_hits = match_symbols(text, symbols) if keyword_result.is_candidate else []
    return MatchResult(
        perpetual_keywords=keyword_result.perpetual_keywords,
        delist_keywords=keyword_result.delist_keywords,
        symbols=symbol_hits,
    )
