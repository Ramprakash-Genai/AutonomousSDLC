# agents/memory_store.py
import json
import os
import time
from urllib.parse import urlparse
from typing import Optional, Dict, List, Any


def _now() -> str:
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
    Page-wise locator memory store

    File layout:
      memory/pages/<page>.locators.json

    Each record schema:
    {
      "page": "<page>",
      "host": "<host>",
      "action": "<action>",
      "target": "<target>",
      "locator": "<selector>",
      "locator_type": "<type>",
      "updated_at": "<timestamp>"
    }
    """

    def __init__(self, base_dir: str = "memory/pages"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _path(self, page: str) -> str:
        return os.path.join(self.base_dir, f"{_safe_page(page)}.locators.json")

    def _load(self, page: str) -> List[Dict[str, Any]]:
        path = self._path(page)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or []
        except Exception:
            return []

    def _save(self, page: str, data: List[Dict[str, Any]]) -> None:
        path = self._path(page)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ----------------------------
    # Read APIs
    # ----------------------------
    def get(
        self, page: str, host: str, action: str, target: str
    ) -> Optional[Dict[str, Any]]:
        """
        Backward-compatible lookup (used by execution runtime)
        """
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

    def find_exact_duplicates(
        self,
        page: str,
        host: str,
        action: str,
        target: str,
        locator: str,
        locator_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Returns all exact duplicate locator records
        (enterprise governance check before save)

        Duplicate key:
        page + host + action + target + locator + locator_type
        locator_type is optional; inferred if not provided.
        """
        page_key = _safe_page(page)
        locator = (locator or "").strip()
        if not locator:
            return []

        # If locator_type not provided, infer it so duplicates still work
        locator_type = (locator_type or infer_locator_type(locator)).strip()

        data = self._load(page_key)
        matches = []
        for item in data:
            if (
                item.get("page") == page_key
                and item.get("host") == host
                and item.get("action") == action
                and item.get("target") == target
                and (item.get("locator") or "").strip() == locator
                and (item.get("locator_type") or "").strip() == locator_type
            ):
                matches.append(item)
        return matches

    # ----------------------------
    # Write APIs (Governed)
    # ----------------------------
    def upsert(
        self,
        page: str,
        host: str,
        action: str,
        target: str,
        locator: str,
        overwrite: bool = False,
        append_new: bool = False,
        locator_type: Optional[str] = None,
    ) -> None:
        """
        Upsert locator entry with governance controls.

        overwrite=True   → replace existing matching (host+action+target)
        append_new=True  → always append as new entry
        default          → overwrite first match if found else append

        locator_type:
        - if provided, persist as-is (normalized)
        - else inferred from locator string
        """
        locator = (locator or "").strip()
        if not locator:
            return

        page_key = _safe_page(page)
        data = self._load(page_key)

        final_type = (locator_type or infer_locator_type(locator)).strip() or "unknown"

        # Exact overwrite by key
        if overwrite:
            for item in data:
                if (
                    item.get("host") == host
                    and item.get("action") == action
                    and item.get("target") == target
                ):
                    item["page"] = page_key
                    item["host"] = host
                    item["action"] = action
                    item["target"] = target
                    item["locator"] = locator
                    item["locator_type"] = final_type
                    item["updated_at"] = _now()
                    self._save(page_key, data)
                    return

        # Append explicitly as new
        if append_new:
            data.append(
                {
                    "page": page_key,
                    "host": host,
                    "action": action,
                    "target": target,
                    "locator": locator,
                    "locator_type": final_type,
                    "updated_at": _now(),
                }
            )
            self._save(page_key, data)
            return

        # Default behavior: upsert (overwrite first match)
        for item in data:
            if (
                item.get("host") == host
                and item.get("action") == action
                and item.get("target") == target
            ):
                item["page"] = page_key
                item["host"] = host
                item["action"] = action
                item["target"] = target
                item["locator"] = locator
                item["locator_type"] = final_type
                item["updated_at"] = _now()
                self._save(page_key, data)
                return

        # Otherwise, append fresh
        data.append(
            {
                "page": page_key,
                "host": host,
                "action": action,
                "target": target,
                "locator": locator,
                "locator_type": final_type,
                "updated_at": _now(),
            }
        )
        self._save(page_key, data)

    def invalidate(self, page: str, host: str, action: str, target: str) -> None:
        """
        Remove matching locator entries (used by healing or manual reset)
        """
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
