import json
import os
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from agents.config import BlueVerseConfig, BlueVerseClient


class PlannerAgent:
    """
    PlannerAgent with local caching to reduce BlueVerse quota usage.
    - Cache key is derived from (step + table + docstring).
    - Cache value is the normalized plan JSON (same output as before).
    """

    def __init__(self):
        self._bv = BlueVerseClient(BlueVerseConfig.from_env())

        # Cache controls
        self.cache_enabled = os.getenv("SDLC_PLANNER_CACHE", "1").strip() == "1"
        self.cache_path = Path(os.getenv("SDLC_PLANNER_CACHE_FILE", "memory/planner_cache.json"))

        # Ensure directory exists
        if self.cache_enabled:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------
    # Cache helpers
    # -------------------------
    def _make_cache_key(self, raw_input: Dict[str, Any]) -> str:
        """
        Stable hash key for the raw planner input.
        """
        payload = json.dumps(raw_input, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
            self.cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            # Cache write failure must not break execution
            pass

    # -------------------------
    # Main planner entry
    # -------------------------
    def plan_step(self, step: str, table=None, docstring=None) -> str:
        table_rows = None
        if table:
            table_rows = [dict(r.items()) for r in table]

        raw_input = {"step": step, "table": table_rows, "docstring": docstring}

        # ✅ Cache lookup
        if self.cache_enabled:
            cache = self._load_cache()
            key = self._make_cache_key(raw_input)
            cached_plan = cache.get(key)
            if isinstance(cached_plan, dict) and cached_plan:
                # Return same format as before (JSON string)
                return json.dumps(cached_plan, ensure_ascii=False)

        # Call BlueVerse planner
        plan = self._bv.plan_step(raw_input)

        # Normalize to the exact keys expected by ExecutionAgent (same as before)
        normalized = {
            "action": plan.get("action"),
            "page": plan.get("page") or "_global",
            "locator_type": plan.get("locator_type", None),
            "target": plan.get("target"),
            "value": plan.get("value"),
            "table": plan.get("table") if plan.get("table") is not None else table_rows,
        }

        # ✅ Cache write-back
        if self.cache_enabled:
            cache = self._load_cache()
            key = self._make_cache_key(raw_input)
            cache[key] = normalized
            self._save_cache(cache)

        return json.dumps(normalized, ensure_ascii=False)