import json
import os
import time
from urllib.parse import urlparse


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_page(page: str) -> str:
    page = (page or "_global").strip().lower().replace(" ", "_")
    return "".join(ch for ch in page if ch.isalnum() or ch in ("_", "-")) or "_global"


def host_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return "unknown"


def infer_locator_type(selector: str) -> str:
    s = (selector or "").strip()
    if not s:
        return "unknown"
    if ">> nth=" in s or "nth=" in s:
        return "nth"
    if s.startswith("xpath=") or s.startswith("//"):
        return "xpath"
    if "get_by_" in s or "getBy" in s:
        return "playwright"
    return "css"


class MemoryStore:
    """
    memory/pages/<page>.locators.json
    Records keyed by: host + action + target
    """

    def __init__(self, base_dir="memory/pages"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, page: str) -> str:
        return os.path.join(self.base_dir, f"{_safe_page(page)}.locators.json")

    def _load(self, page: str):
        path = self._path(page)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []

    def _save(self, page: str, data):
        path = self._path(page)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, page: str, host: str, action: str, target: str):
        data = self._load(page)
        for item in data:
            if (
                item.get("host") == host
                and item.get("action") == action
                and item.get("target") == target
            ):
                loc = (item.get("locator") or "").strip()
                if loc:
                    return item
        return None

    def upsert(self, page: str, host: str, action: str, target: str, locator: str):
        locator = (locator or "").strip()
        if not locator:
            return
        data = self._load(page)
        for item in data:
            if (
                item.get("host") == host
                and item.get("action") == action
                and item.get("target") == target
            ):
                item["locator"] = locator
                item["locator_type"] = infer_locator_type(locator)
                item["updated_at"] = _now()
                self._save(page, data)
                return

        data.append(
            {
                "page": _safe_page(page),
                "host": host,
                "action": action,
                "target": target,
                "locator": locator,
                "locator_type": infer_locator_type(locator),
                "updated_at": _now(),
            }
        )
        self._save(page, data)

    def invalidate(self, page: str, host: str, action: str, target: str):
        data = self._load(page)
        new_data = [
            d
            for d in data
            if not (
                d.get("host") == host
                and d.get("action") == action
                and d.get("target") == target
            )
        ]
        self._save(page, new_data)