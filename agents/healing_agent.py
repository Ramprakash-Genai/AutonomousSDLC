import os
import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.config import BlueVerseConfig, BlueVerseClient


class HealingAgent:
    """
    HealingAgent with local caching to reduce BlueVerse quota usage.

    Cache key is derived from:
      - target, action, locator_type, page_url, error
      - plus a DOM fingerprint (sha256 of truncated DOM)

    Cache value:
      - cleaned list[str] of candidates (same as current behavior)

    Env toggles:
      - SDLC_HEALING_CACHE=1 (default) enables cache
      - SDLC_HEALING_CACHE_FILE=memory/healing_cache.json (default)
    """

    def __init__(self):
        self._bv = BlueVerseClient(BlueVerseConfig.from_env())

        self.cache_enabled = os.getenv("SDLC_HEALING_CACHE", "1").strip() == "1"
        self.cache_path = Path(
            os.getenv("SDLC_HEALING_CACHE_FILE", "memory/healing_cache.json")
        )

        if self.cache_enabled:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------
    # Cache helpers
    # -------------------------
    def _dom_fingerprint(self, dom: str) -> str:
        """
        Fingerprint DOM without storing full DOM as part of cache key.
        """
        d = (dom or "")[:16000]
        return hashlib.sha256(d.encode("utf-8", errors="ignore")).hexdigest()

    def _make_cache_key(self, payload: Dict[str, Any], dom_fp: str) -> str:
        """
        Stable cache key built from payload without full dom content.
        """
        key_payload = {
            "target": payload.get("target"),
            "action": payload.get("action"),
            "locator_type": payload.get("locator_type"),
            "page_url": payload.get("page_url"),
            "error": payload.get("error"),
            "dom_fp": dom_fp,
        }
        raw = json.dumps(key_payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_enabled:
            return {}
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        if not self.cache_enabled:
            return
        try:
            self.cache_path.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            # Cache write must not break execution
            pass

    # -------------------------
    # Main Healing call
    # -------------------------
    def suggest_candidates(
        self,
        dom: str,
        target: str,
        action: str,
        page_url: str,
        locator_type: str = None,
        error: str = "action_failed",
    ) -> List[str]:

        payload = {
            "dom": (dom or "")[:16000],
            "target": target,
            "action": action,
            "locator_type": locator_type,
            "page_url": page_url,
            "error": error,
        }

        # ✅ Cache lookup
        dom_fp = self._dom_fingerprint(dom)
        if self.cache_enabled:
            cache = self._load_cache()
            key = self._make_cache_key(payload, dom_fp)
            cached = cache.get(key)
            if isinstance(cached, list):
                # Return cached candidates directly (already cleaned)
                return [str(x) for x in cached if isinstance(x, str) and x.strip()]

        # Call BlueVerse healing agent
        candidates = self._bv.healing_candidates(payload)

        # Clean output (same behavior as your existing file)
        cleaned: List[str] = []
        for c in candidates:
            c = (c or "").strip().strip('"').strip("'")
            if not c:
                continue
            if ">>" in c:
                continue
            if c not in cleaned:
                cleaned.append(c)

        # ✅ Cache write-back
        if self.cache_enabled:
            cache = self._load_cache()
            key = self._make_cache_key(payload, dom_fp)
            cache[key] = cleaned
            self._save_cache(cache)

        return cleaned
