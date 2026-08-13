from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from .http_client import HttpClient
from .models import AnnouncementDetail, AnnouncementItem
from .utils import clean_html_text, compact_text


def _extract_json_script(html: str, script_id: str):
    pattern = r'<script[^>]+id="%s"[^>]*>(.*?)</script>' % re.escape(script_id)
    match = re.search(pattern, html, flags=re.S | re.I)
    if not match:
        return None
    raw = match.group(1).strip()
    if not raw:
        return None
    return json.loads(raw)


def _looks_like_waf_challenge(html: str) -> bool:
    lowered = html.lower()
    markers = [
        "x-amzn-waf-action",
        "window.awswafcookiedomainlist",
        "window.gokuprops",
        "aws waf",
        "request blocked",
        "challenge",
    ]
    return any(marker in lowered for marker in markers)


class BinanceAnnouncementClient:
    def __init__(self, http: HttpClient, list_url: str):
        self.http = http
        self.list_url = list_url

    def fetch_latest_items(self, page_no: int = 1, page_size: int = 20, article_type: int = 1) -> List[AnnouncementItem]:
        params = {"type": article_type, "pageNo": page_no, "pageSize": page_size}
        headers = {"clienttype": "web", "Accept": "application/json"}
        payload = self.http.get_json(self.list_url, params=params, headers=headers)
        data = payload.get("data", {})
        items: List[AnnouncementItem] = []
        for catalog in data.get("catalogs", []):
            catalog_id = catalog.get("catalogId")
            catalog_name = catalog.get("catalogName", "")
            for article in catalog.get("articles", []):
                items.append(
                    AnnouncementItem(
                        article_id=int(article["id"]),
                        code=str(article.get("code", "")),
                        title=str(article.get("title", "")).strip(),
                        release_ts=int(article.get("releaseDate", 0)),
                        catalog_id=catalog_id,
                        catalog_name=catalog_name,
                        source_page=page_no,
                    )
                )
        items.sort(key=lambda x: x.release_ts, reverse=True)
        return items

    def fetch_items(self, max_pages: int = 3, page_size: int = 20, article_type: int = 1) -> List[AnnouncementItem]:
        collected: List[AnnouncementItem] = []
        for page_no in range(1, max_pages + 1):
            try:
                items = self.fetch_latest_items(page_no=page_no, page_size=page_size, article_type=article_type)
            except Exception:
                continue
            collected.extend(items)
        dedup: Dict[str, AnnouncementItem] = {}
        for item in collected:
            dedup[item.dedupe_key] = item
        merged = list(dedup.values())
        merged.sort(key=lambda x: x.release_ts, reverse=True)
        return merged

    def build_official_url(self, item: AnnouncementItem) -> str:
        return f"https://www.binance.com/en/support/announcement/detail/{item.code}"

    def fetch_official_detail(self, item: AnnouncementItem) -> Optional[AnnouncementDetail]:
        url = self.build_official_url(item)
        headers = {"clienttype": "web"}
        try:
            html = self.http.get_text(url, headers=headers)
        except Exception:
            return None
        if not html or _looks_like_waf_challenge(html):
            return None
        text = clean_html_text(html)
        if not text or _looks_like_waf_challenge(text):
            return None
        return AnnouncementDetail(
            title=item.title,
            publish_time=item.release_time,
            url=url,
            full_text=text,
            body_source="binance_html",
        )


class MirrorAnnouncementClient:
    def __init__(self, http: HttpClient, latest_url: str, detail_template: str):
        self.http = http
        self.latest_url = latest_url
        self.detail_template = detail_template
        self._index_cache = None

    def _load_latest(self):
        html = self.http.get_text(self.latest_url, headers={"Accept": "text/html"})
        data = _extract_json_script(html, "announcementsData")
        if not isinstance(data, list):
            return []
        return data

    def refresh_index(self):
        latest = self._load_latest()
        index = {}
        for item in latest:
            title = str(item.get("title", "")).strip()
            key = compact_text(title)
            if key and key not in index:
                index[key] = item
        self._index_cache = index
        return index

    def _ensure_index(self):
        if self._index_cache is None:
            return self.refresh_index()
        return self._index_cache

    def find_article(self, title: str):
        index = self._ensure_index()
        key = compact_text(title)
        return index.get(key)

    def fetch_detail_by_title(self, title: str) -> Optional[AnnouncementDetail]:
        item = self.find_article(title)
        if not item:
            return None
        article_id = item.get("id")
        if article_id is None:
            return None
        url = self.detail_template.format(article_id=article_id)
        html = self.http.get_text(url, headers={"Accept": "text/html"})
        data = _extract_json_script(html, "announcementData")
        if not isinstance(data, dict):
            return None
        body = str(data.get("body", "")).strip()
        publish_ts = int(data.get("publishDate", item.get("publishDate", 0)))
        title_value = str(data.get("title", title)).strip()
        if not body:
            return None
        return AnnouncementDetail(
            title=title_value,
            publish_time=datetime.utcfromtimestamp(publish_ts / 1000.0) if publish_ts else datetime.utcnow(),
            url=url,
            full_text=clean_html_text(body),
            body_source="mirror_html",
        )

    def fetch_detail(self, title: str) -> Optional[AnnouncementDetail]:
        try:
            return self.fetch_detail_by_title(title)
        except Exception:
            return None
