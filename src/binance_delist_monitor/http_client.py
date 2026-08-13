from __future__ import annotations

from typing import Any, Dict, Optional

import requests


class HttpError(RuntimeError):
    pass


class HttpClient:
    def __init__(self, timeout_seconds: int = 20, verify_ssl: bool = False):
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout_seconds, verify=self.verify_ssl)
        response.raise_for_status()
        try:
            return response.json()
        except Exception as exc:
            raise HttpError("failed to decode json from %s: %s" % (url, exc)) from exc

    def get_text(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> str:
        response = self.session.get(url, params=params, headers=headers, timeout=self.timeout_seconds, verify=self.verify_ssl)
        response.raise_for_status()
        return response.text
