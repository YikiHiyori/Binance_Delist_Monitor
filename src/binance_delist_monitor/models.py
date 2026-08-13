from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class AnnouncementItem:
    article_id: int
    code: str
    title: str
    release_ts: int
    catalog_id: Optional[int] = None
    catalog_name: str = ""
    source_page: int = 1

    @property
    def release_time(self) -> datetime:
        return datetime.utcfromtimestamp(self.release_ts / 1000.0)

    @property
    def dedupe_key(self) -> str:
        return self.code or f"{self.article_id}:{self.title}:{self.release_ts}"


@dataclass
class AnnouncementDetail:
    title: str
    publish_time: datetime
    url: str
    full_text: str
    body_source: str


@dataclass
class MatchResult:
    perpetual_keywords: List[str]
    delist_keywords: List[str]
    symbols: List[str]

    @property
    def is_candidate(self) -> bool:
        return bool(self.perpetual_keywords and self.delist_keywords)
