import re
from typing import List, Optional, Tuple

# Playwright sync ElementHandle is used indirectly via locator.element_handles()
# No extra dependencies needed.

CONTROL_KINDS = {
    "textbox": "input, textarea, [contenteditable='true'], oj-input-text input",
    "inputbox": "input, textarea, [contenteditable='true'], oj-input-text input",
    "textarea": "textarea",
    "button": "button, [role='button'], input[type='button'], input[type='submit']",
    "link": "a, [role='link']",
    "dropdown": "select, [role='combobox'], [role='listbox']",
    "combobox": "[role='combobox'], select",
    "checkbox": "input[type='checkbox'], [role='checkbox']",
    "radio": "input[type='radio'], [role='radio']",
    "tab": "[role='tab']",
    "element": "*",
    "text": "*",
}

DIRECTION_SYNONYMS = {
    "below": ["below", "under", "beneath", "down", "bottom", "lower"],
    "above": ["above", "over", "top", "upper"],
    "left": ["left", "left_of", "to the left", "left side"],
    "right": ["right", "right_of", "to the right", "right side"],
    "next_to": ["next_to", "next to", "beside", "adjacent"],
    "near": ["near", "nearby", "around"],
    "within": [
        "within",
        "inside",
        "in",
        "in the",
        "section",
        "panel",
        "card",
        "modal",
        "dialog",
    ],
    "before": ["before"],
    "after": ["after"],
}

_TARGET_ANCHOR_RE = re.compile(
    r"^(?P<kind>textbox|inputbox|textarea|button|link|dropdown|combobox|checkbox|radio|tab|element|text)\s+"
    r'(?P<direction>below|above|left|right|next_to|near|within|inside|before|after)\s+text\s+"(?P<anchor>[^"]+)"',
    re.IGNORECASE,
)

_PROX_RE = re.compile(
    r"\b(immediate|immediately|direct|directly|just)\b", re.IGNORECASE
)


def _normalize_direction(s: str) -> str:
    s = (s or "").strip().lower()
    for canonical, words in DIRECTION_SYNONYMS.items():
        for w in words:
            if w == s or w in s:
                return canonical
    return "near"


def _is_immediate(s: str) -> bool:
    return bool(_PROX_RE.search(s or ""))


def _safe_xpath_literal(text: str) -> str:
    # Produce an XPath literal safe for quotes
    if '"' not in text:
        return f'"{text}"'
    parts = text.split('"')
    # concat("a", '"', "b", '"', "c")
    concat_parts = []
    for i, p in enumerate(parts):
        if p:
            concat_parts.append(f'"{p}"')
        if i != len(parts) - 1:
            concat_parts.append("'\"'")
    return "concat(" + ", ".join(concat_parts) + ")"


class VisionLocatorAgent:
    """
    Vision-like locator resolver using UI geometry (bounding boxes) + DOM.
    It DOES NOT require external vision models.
    It returns executable selectors (mostly xpath=...) to be used with page.locator().
    """

    def suggest_candidates(
        self,
        page,
        target: str,
        action: str,
        screenshot_path: Optional[str] = None,
        max_candidates: int = 5,
        scan_limit: int = 60,
    ) -> List[str]:
        """
        Returns a list of selector strings ordered best->worst.
        """
        t = (target or "").strip()
        if not t:
            return []

        # Always capture screenshot if path is given (audit/debug)
        if screenshot_path:
            try:
                page.screenshot(path=screenshot_path, full_page=True)
            except Exception:
                pass

        # Handle explicit fallback targets
        if t.lower().startswith("textbox first_visible") or t.lower().startswith(
            "dropdown first_visible"
        ):
            return self._first_visible_candidates(
                page, t, max_candidates=max_candidates
            )

        parsed = self._parse_target(t)
        if not parsed:
            return []

        kind, direction, anchor = parsed
        direction = _normalize_direction(direction)
        immediate = _is_immediate(t)

        # Find anchor element (by visible text) and its bounding box
        anchor_loc = page.get_by_text(anchor, exact=False).first
        try:
            anchor_loc.wait_for(state="visible", timeout=60000)
        except Exception:
            return []

        try:
            anchor_box = anchor_loc.bounding_box()
        except Exception:
            anchor_box = None

        if not anchor_box:
            return []

        # Candidate selector pool based on control kind
        css = CONTROL_KINDS.get(kind.lower(), CONTROL_KINDS["element"])
        cand_locator = page.locator(css)
        try:
            handles = cand_locator.element_handles()
        except Exception:
            return []

        # Score candidates by direction using bounding boxes
        scored: List[Tuple[float, str]] = []
        count = 0

        for h in handles:
            if count >= scan_limit:
                break
            count += 1
            try:
                box = h.bounding_box()
                if not box:
                    continue
                # Filter out non-visible tiny boxes
                if box.get("width", 0) < 2 or box.get("height", 0) < 2:
                    continue

                score = self._score(anchor_box, box, direction, immediate)
                if score is None:
                    continue

                # Compute a unique XPath for this element
                xpath = h.evaluate(
                    """(el) => {
                        function xpathFor(node) {
                            if (node.id) {
                                // If id exists, use id-based XPath (safe and short)
                                return '//*[@id="' + node.id + '"]';
                            }
                            const parts = [];
                            while (node && node.nodeType === Node.ELEMENT_NODE) {
                                let ix = 1;
                                let sib = node.previousElementSibling;
                                while (sib) { 
                                    if (sib.nodeName === node.nodeName) ix++;
                                    sib = sib.previousElementSibling;
                                }
                                parts.unshift(node.nodeName.toLowerCase() + '[' + ix + ']');
                                node = node.parentElement;
                            }
                            return '/' + parts.join('/');
                        }
                        return xpathFor(el);
                    }"""
                )
                if xpath and isinstance(xpath, str):
                    scored.append((score, f"xpath={xpath}"))
            except Exception:
                continue

        # Add a few deterministic anchor-based XPaths as backup (very effective on custom DOMs)
        scored.extend(self._anchor_xpath_backups(kind, direction, anchor, immediate))

        # Sort by score and return top unique selectors
        scored.sort(key=lambda x: x[0])
        out: List[str] = []
        seen = set()
        for _, sel in scored:
            sel = (sel or "").strip()
            if not sel or sel in seen:
                continue
            out.append(sel)
            seen.add(sel)
            if len(out) >= max_candidates:
                break
        return out

    def _parse_target(self, target: str) -> Optional[Tuple[str, str, str]]:
        m = _TARGET_ANCHOR_RE.search(target)
        if not m:
            return None
        kind = (m.group("kind") or "").strip()
        direction = (m.group("direction") or "").strip()
        anchor = (m.group("anchor") or "").strip()
        if not (kind and direction and anchor):
            return None
        return kind, direction, anchor

    def _score(
        self, a: dict, b: dict, direction: str, immediate: bool
    ) -> Optional[float]:
        """
        Lower score is better.
        Uses geometry rules to rank candidates.
        """
        ax, ay, aw, ah = a["x"], a["y"], a["width"], a["height"]
        bx, by, bw, bh = b["x"], b["y"], b["width"], b["height"]

        a_right = ax + aw
        a_bottom = ay + ah
        b_right = bx + bw
        b_bottom = by + bh

        # Distance helpers
        def horiz_gap():
            if bx > a_right:
                return bx - a_right
            if ax > b_right:
                return ax - b_right
            return 0

        def vert_gap():
            if by > a_bottom:
                return by - a_bottom
            if ay > b_bottom:
                return ay - b_bottom
            return 0

        center_dx = (bx + bw / 2) - (ax + aw / 2)
        center_dy = (by + bh / 2) - (ay + ah / 2)

        if direction == "below":
            if by <= a_bottom:
                return None
            # Prefer minimal vertical distance and good horizontal alignment
            return (by - a_bottom) + abs(center_dx) * 0.2 + (0 if not immediate else 0)

        if direction == "above":
            if b_bottom >= ay:
                return None
            return (ay - b_bottom) + abs(center_dx) * 0.2 + (0 if not immediate else 0)

        if direction == "left":
            if b_right >= ax:
                return None
            return (ax - b_right) + abs(center_dy) * 0.2

        if direction == "right":
            if bx <= a_right:
                return None
            return (bx - a_right) + abs(center_dy) * 0.2

        if direction in ("next_to", "near"):
            # Nearest Euclidean-like distance
            return (horiz_gap() ** 2 + vert_gap() ** 2) ** 0.5 + (
                abs(center_dx) + abs(center_dy)
            ) * 0.01

        if direction in ("within", "inside"):
            # Prefer things that overlap anchor's bounding box region (or close)
            overlap_x = max(0, min(a_right, b_right) - max(ax, bx))
            overlap_y = max(0, min(a_bottom, b_bottom) - max(ay, by))
            overlap_area = overlap_x * overlap_y
            if overlap_area <= 0:
                return None
            # Higher overlap -> smaller score
            return 1.0 / (overlap_area + 1.0)

        if direction == "before":
            # Before in layout ≈ above or left; prioritize above
            if b_bottom < ay:
                return (ay - b_bottom) + abs(center_dx) * 0.2
            return None

        if direction == "after":
            if by > a_bottom:
                return (by - a_bottom) + abs(center_dx) * 0.2
            return None

        return None

    def _anchor_xpath_backups(
        self, kind: str, direction: str, anchor: str, immediate: bool
    ) -> List[Tuple[float, str]]:
        """
        Deterministic fallbacks using anchor text and XPath axes.
        These are extremely effective for custom component DOMs.
        """
        node = (
            "input|textarea"
            if kind.lower() in ("textbox", "inputbox", "textarea")
            else "*"
        )
        a = _safe_xpath_literal(anchor)
        anchor_xpath = f"//*[contains(normalize-space(.), {a})]"

        if direction == "below":
            if immediate:
                xp = f"{anchor_xpath}/following-sibling::*//({node})[1]"
            else:
                xp = f"{anchor_xpath}/following::({node})[1]"
            return [(5.0, f"xpath={xp}")]

        if direction == "above":
            if immediate:
                xp = f"{anchor_xpath}/preceding-sibling::*//({node})[1]"
            else:
                xp = f"{anchor_xpath}/preceding::({node})[1]"
            return [(5.0, f"xpath={xp}")]

        if direction in ("left", "right", "next_to", "near", "within", "inside"):
            xp = f"{anchor_xpath}/ancestor::*[1]//({node})[1]"
            return [(6.0, f"xpath={xp}")]

        return []

    def _first_visible_candidates(
        self, page, target: str, max_candidates: int = 5
    ) -> List[str]:
        # Very generic fallbacks used only when the step explicitly requested generic.
        t = (target or "").lower()
        if "dropdown" in t:
            return ["select", "[role='combobox']", "[role='listbox']"][:max_candidates]
        return [
            "input:not([type='hidden']):not([disabled])",
            "textarea:not([disabled])",
            "[contenteditable='true']",
            "oj-input-text input",
        ][:max_candidates]
