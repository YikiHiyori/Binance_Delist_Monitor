from __future__ import annotations

import html
import re
from typing import Iterable, List, Sequence


def normalize_unicode_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("Ⓢ", "S")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value


def compact_text(value: str) -> str:
    value = normalize_unicode_text(value).upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


def tokenized_upper_text(value: str) -> str:
    value = normalize_unicode_text(value).upper()
    return re.sub(r"[^A-Z0-9]+", " ", value)


def clean_html_text(value: str) -> str:
    value = normalize_unicode_text(value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s+", "\n", value)
    return value.strip()


def unique_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    result = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def join_nonempty(parts: Iterable[str], sep: str = " ") -> str:
    return sep.join([p for p in parts if p])
