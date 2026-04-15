# agents/locator_agent.py
import json
import os
import hashlib
from pathlib import Path
from urllib.parse import urlparse
import re
from typing import List, Optional

from agents.config import BlueVerseConfig, BlueVerseClient

_ANCHOR_RE = re.compile(
    r'^\s*(below|above|within|inside)\s+text\s+"([^"]+)"\s*\.?\s*$',
    re.IGNORECASE,
)


class LocatorAgent:
    """
    Universal Locator Agent wrapper.

    Strategy (universal):
      1) Cache (optional)
      2) BlueVerse locator candidates
      3) Deterministic augmentation (role/label/attrs/xpath, anchor parsing)

    Env:
      SDLC_LOCATOR_CACHE=1
      SDLC_LOCATOR_CACHE_FILE=memory/locator_cache.json
    """

    def __init__(self):
        self._bv = BlueVerseClient(BlueVerseConfig.from_env())
        self.cache_enabled = os.getenv("SDLC_LOCATOR_CACHE", "1").strip() == "1"
        self.cache_file = Path(
            os.getenv("SDLC_LOCATOR_CACHE_FILE", "memory/locator_cache.json")
        )
        if self.cache_enabled:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _host_from_url(url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"

    @staticmethod
    def _dom_fingerprint(dom: str) -> str:
        d = (dom or "")[:16000]
        return hashlib.sha256(d.encode("utf-8", errors="ignore")).hexdigest()

    def _load_cache(self) -> dict:
        if not self.cache_enabled or not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _save_cache(self, cache: dict) -> None:
        if not self.cache_enabled:
            return
        try:
            self.cache_file.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _cache_key(
        self, host: str, action: str, locator_type: str, target: str, dom_fp: str
    ) -> str:
        payload = {
            "host": host,
            "action": action or "",
            "locator_type": locator_type or "",
            "target": target or "",
            "dom_fp": dom_fp,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _unique(items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items or []:
            x = (x or "").strip().strip('"').strip("'")
            if not x:
                continue
            if ">>" in x:
                continue
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    @staticmethod
    def _esc_q(s: str) -> str:
        return (
            (s or "").replace('"', '\\"').replace("\n", " ").replace("\r", " ").strip()
        )

    @staticmethod
    def _xpath_literal(text: str) -> str:
        if '"' not in text:
            return f'"{text}"'
        parts = text.split('"')
        concat_parts = []
        for i, p in enumerate(parts):
            if p:
                concat_parts.append(f'"{p}"')
            if i != len(parts) - 1:
                concat_parts.append("'\"'")
        return "concat(" + ", ".join(concat_parts) + ")"

    def _role_for(self, locator_type: Optional[str], action: str) -> Optional[str]:
        lt = (locator_type or "").strip().lower()
        action = (action or "").strip().lower()
        if lt in ("link", "button", "tab", "checkbox", "radio", "combobox"):
            return lt
        if lt == "dropdown":
            return "button"
        if lt == "header":
            return "heading"
        if action == "input":
            return "textbox"
        if action == "click":
            return "button"
        if action == "select":
            return "combobox"
        return None

    def _deterministic_candidates(
        self, target: str, action: str, locator_type: Optional[str]
    ) -> List[str]:
        t = (target or "").strip()
        if not t:
            return []

        tq = self._esc_q(t)
        lit = self._xpath_literal(t)
        cands: List[str] = []

        # Anchor parsing if target is like: below text "X"
        m = _ANCHOR_RE.match(t)
        if m:
            direction = m.group(1).lower()
            anchor_text = m.group(2).strip()
            alit = self._xpath_literal(anchor_text)
            anchor_contains = f"(//*[contains(normalize-space(.), {alit})])[1]"
            if action in ("input", "select"):
                if direction == "below":
                    cands.extend(
                        [
                            f"xpath={anchor_contains}/following::input[not(@type='hidden')][1]",
                            f"xpath={anchor_contains}/following::textarea[1]",
                        ]
                    )
                elif direction == "above":
                    cands.extend(
                        [
                            f"xpath={anchor_contains}/preceding::input[not(@type='hidden')][1]",
                            f"xpath={anchor_contains}/preceding::textarea[1]",
                        ]
                    )
                else:
                    cands.extend(
                        [
                            f"xpath={anchor_contains}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                            "//input[not(@type='hidden')][1]",
                            f"xpath={anchor_contains}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                            "//textarea[1]",
                        ]
                    )

        role = self._role_for(locator_type, action)
        if role:
            cands.append(f'role={role}[name="{tq}"]')

        if action in ("input", "select"):
            cands.extend(
                [
                    f'label="{tq}"',
                    f'placeholder="{tq}"',
                    f"xpath=(//label[normalize-space(.)={lit}])[1]/following::input[1]",
                    f"xpath=(//label[normalize-space(.)={lit}])[1]/following::textarea[1]",
                    f"xpath=(//*[normalize-space(.)={lit}])[1]/following::input[1]",
                ]
            )

        if action == "click":
            cands.append(
                f"xpath=(//*[contains(normalize-space(.), {lit})])[1]"
                "/ancestor-or-self::*[self::a or self::button or @role='button' or @role='link' "
                "or @role='menuitem' or @onclick or @tabindex='0'][1]"
            )

        # attribute fallbacks
        cands.extend(
            [
                f'[aria-label="{t}"]',
                f'[title="{t}"]',
                f'[name="{t}"]',
                f'[placeholder="{t}"]',
                f'text="{t}"',
            ]
        )

        # robust assert helpers
        if action == "assert":
            key = t[:40].rstrip() if len(t) > 60 else t
            cands.extend(
                [
                    f"text={self._esc_q(t)}",
                    f"xpath=//*[contains(normalize-space(.), {self._xpath_literal(key)})]",
                ]
            )

        return self._unique(cands)

    def generate_locator(
        self,
        dom: str,
        target: str,
        action: str,
        page_url: str,
        locator_type: str = None,
    ) -> str:
        host = self._host_from_url(page_url)
        dom_fp = self._dom_fingerprint(dom)
        key = self._cache_key(host, action, locator_type, target, dom_fp)

        # 1) cache
        if self.cache_enabled:
            cache = self._load_cache()
            cached = cache.get(key)
            if isinstance(cached, str) and cached.strip():
                return cached.strip()

        # 2) BlueVerse candidates
        payload = {
            "dom": (dom or "")[:16000],
            "target": target,
            "action": action,
            "locator_type": locator_type,
            "page_url": page_url,
        }

        candidates: List[str] = []
        try:
            candidates = self._bv.locator_candidates(payload)
        except Exception:
            candidates = []

        # 3) deterministic augmentation (cold-start safe)
        candidates.extend(self._deterministic_candidates(target, action, locator_type))

        final = "\n\n".join(self._unique(candidates))

        # cache write
        if self.cache_enabled:
            cache = self._load_cache()
            cache[key] = final
            self._save_cache(cache)

        return final
