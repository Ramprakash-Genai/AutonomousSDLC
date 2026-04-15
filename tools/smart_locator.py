# tools/smart_locator.py
import re
from typing import Optional, List

# Anchor targets like:
#   below text "Enter the bypass code."
#   below text "Enter the bypass code"
#   below text "Enter the bypass code".   (dot outside quotes)
#   below text "Enter the bypass code."   (dot inside quotes)
_ANCHOR_RE = re.compile(
    r'^\s*(below|above|within|inside)\s+text\s+"([^"]+)"\s*\.?\s*$',
    re.IGNORECASE,
)


def _css_attr(attr: str, value: str) -> str:
    """Safe CSS attribute selector."""
    v = value or ""
    v = v.replace("\\", "\\\\")
    v = v.replace('"', '\\"')
    v = v.replace("\n", " ").replace("\r", " ").strip()
    return f'[{attr}="{v}"]'


def _pw_text_exact(text: str) -> str:
    """Playwright text engine exact match."""
    t = (text or "").replace('"', '\\"')
    t = t.replace("\n", " ").replace("\r", " ").strip()
    return f'text="{t}"' if t else 'text=""'


def _esc_q(s: str) -> str:
    """Escape for Playwright selector engines."""
    return (s or "").replace('"', '\\"').replace("\n", " ").replace("\r", " ").strip()


def _xpath_literal(text: str) -> str:
    """Safe XPath literal for arbitrary text (handles quotes)."""
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


class SmartLocatorResolver:
    """
    Universal deterministic locator resolver.

    Policy (universal):
      1) Accessibility-first: role+name, label, placeholder
      2) DOM attributes: data-testid, aria-label, title, name, placeholder
      3) Generic XPath: label->input, anchor below/above/within, clickable-ancestor for click
      4) Text fallback

    Returns multi-candidate selectors separated by "\\n\\n".
    """

    def _unique(self, items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items or []:
            x = (x or "").strip()
            if x and x not in seen:
                out.append(x)
                seen.add(x)
        return out

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

    def _anchor_candidates(
        self, direction: str, anchor_text: str, action: str
    ) -> List[str]:
        """Universal anchor resolver (no hardcoding)."""
        anchor = (anchor_text or "").strip()
        if not anchor:
            return []

        lit = _xpath_literal(anchor)
        anchor_exact = f"(//*[normalize-space(.)={lit}])[1]"
        anchor_contains = f"(//*[contains(normalize-space(.), {lit})])[1]"

        cands: List[str] = []

        if action in ("input", "select"):
            if direction == "below":
                cands.extend(
                    [
                        f"xpath={anchor_exact}/following::input[not(@type='hidden')][1]",
                        f"xpath={anchor_exact}/following::textarea[1]",
                        f"xpath={anchor_contains}/following::input[not(@type='hidden')][1]",
                        f"xpath={anchor_contains}/following::textarea[1]",
                    ]
                )
            elif direction == "above":
                cands.extend(
                    [
                        f"xpath={anchor_exact}/preceding::input[not(@type='hidden')][1]",
                        f"xpath={anchor_exact}/preceding::textarea[1]",
                        f"xpath={anchor_contains}/preceding::input[not(@type='hidden')][1]",
                        f"xpath={anchor_contains}/preceding::textarea[1]",
                    ]
                )
            else:
                cands.extend(
                    [
                        f"xpath={anchor_exact}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                        "//input[not(@type='hidden')][1]",
                        f"xpath={anchor_exact}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                        "//textarea[1]",
                        f"xpath={anchor_contains}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                        "//input[not(@type='hidden')][1]",
                    ]
                )

        if action == "click":
            if direction == "below":
                cands.append(
                    f"xpath={anchor_contains}/following::*[self::a or self::button or @role='button' or @role='link' "
                    "or @onclick or @tabindex='0'][1]"
                )
            elif direction == "above":
                cands.append(
                    f"xpath={anchor_contains}/preceding::*[self::a or self::button or @role='button' or @role='link' "
                    "or @onclick or @tabindex='0'][1]"
                )
            else:
                cands.append(
                    f"xpath={anchor_contains}/ancestor-or-self::*[self::div or self::section or self::form][1]"
                    "//*[self::a or self::button or @role='button' or @role='link' or @onclick or @tabindex='0'][1]"
                )

        return self._unique(cands)

    def resolve(
        self, page, target: str, action: str, locator_type: Optional[str] = None
    ) -> Optional[str]:
        target = (target or "").strip()
        action = (action or "").strip().lower()
        locator_type = (locator_type or "").strip().lower() or None

        if not target:
            return None

        tq = _esc_q(target)
        cands: List[str] = []

        # 0) Anchor parsing (universal)
        m = _ANCHOR_RE.match(target)
        if m:
            direction = m.group(1).lower()
            anchor_text = m.group(2)
            cands.extend(self._anchor_candidates(direction, anchor_text, action))

        # 1) ASSERT: tolerant + exact fallback (universal)
        if action == "assert":
            cands.append(f"text={tq}")
            key = target[:40].rstrip() if len(target) > 60 else target
            cands.append(
                f"xpath=//*[contains(normalize-space(.), {_xpath_literal(key)})]"
            )
            cands.append(_pw_text_exact(target))
            cands = self._unique(cands)
            return "\n\n".join(cands) if len(cands) > 1 else cands[0]

        # 2) Accessibility-first (role/name/label/placeholder)
        role = self._role_for(locator_type, action)
        if role:
            cands.append(f'role={role}[name="{tq}"]')

        if action in ("input", "select"):
            cands.extend([f'label="{tq}"', f'placeholder="{tq}"'])

        # 3) DOM attributes
        cands.extend(
            [
                _css_attr("data-testid", target),
                _css_attr("aria-label", target),
                _css_attr("title", target),
                _css_attr("name", target),
                _css_attr("placeholder", target),
            ]
        )

        # 4) Label->input XPath fallback (universal)
        lit = _xpath_literal(target)
        if action in ("input", "select"):
            cands.extend(
                [
                    f"xpath=(//label[normalize-space(.)={lit}])[1]/following::input[1]",
                    f"xpath=(//label[normalize-space(.)={lit}])[1]/following::textarea[1]",
                    f"xpath=(//*[normalize-space(.)={lit}])[1]/following::input[1]",
                ]
            )

        # 5) Clickable ancestor (universal)
        if action == "click":
            cands.append(
                f"xpath=(//*[contains(normalize-space(.), {lit})])[1]"
                "/ancestor-or-self::*[self::a or self::button or @role='button' or @role='link' "
                "or @role='menuitem' or @onclick or @tabindex='0'][1]"
            )

        # 6) Text fallback (exact)
        cands.append(_pw_text_exact(target))

        cands = self._unique(cands)
        return "\n\n".join(cands) if len(cands) > 1 else (cands[0] if cands else None)
