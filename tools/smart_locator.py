# tools/smart_locator.py
# Universal deterministic locator resolver (non-hardcoded)
# Generates ranked Playwright selector candidates for a given (action, locator_type, target, value)

import re
from typing import List, Optional, Dict, Any


# Anchor targets like:
#   below text "Enter the bypass code."
#   above text "Category"
#   within text "Some label"
_ANCHOR_RE = re.compile(
    r'^\s*(below|above|within|inside)\s+text\s+"([^"]+)"\s*\.?\s*$',
    re.IGNORECASE,
)


def _esc_css_value(value: str) -> str:
    """Escape CSS attribute value safely."""
    v = value or ""
    v = v.replace("\\", "\\\\")
    v = v.replace('"', '\\"')
    v = v.replace("\n", " ").replace("\r", " ").strip()
    return v


def _css_attr(attr: str, value: str) -> str:
    """Safe CSS attribute selector."""
    v = _esc_css_value(value)
    if not v:
        return ""
    return f'css=[{attr}="{v}"]'


def _esc_text_value(text: str) -> str:
    """Escape text for Playwright text engines."""
    t = text or ""
    t = t.replace('"', '\\"')
    t = t.replace("\n", " ").replace("\r", " ").strip()
    return t


def _pw_text_exact(text: str) -> str:
    """Playwright text selector exact match."""
    t = _esc_text_value(text)
    return f'text="{t}"' if t else ""


def _pw_text_loose(text: str) -> str:
    """Playwright text selector loose match."""
    t = _esc_text_value(text)
    return f"text={t}" if t else ""


def _xpath_literal(text: str) -> str:
    """Safe XPath literal for arbitrary text (handles quotes)."""
    if text is None:
        text = ""
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


def _role_selector(role: str, name: str, exact: bool = False) -> str:
    """
    Playwright role selector engine format:
      role=button[name="Save"]
    exact match is handled by name matching strategy in executor; here we keep consistent.
    """
    n = _esc_text_value(name)
    if not n:
        return f"role={role}"
    # Use quoted name; executor may try exact/loose variants elsewhere.
    return f'role={role}[name="{n}"]'


def _candidate_list(*items: str) -> List[str]:
    return [x for x in items if x and isinstance(x, str) and x.strip()]


class SmartLocatorResolver:
    """
    Universal deterministic locator resolver.

    It returns a single string that may contain multiple candidate selectors separated by blank lines.
    Your execution engine should try candidates in order.
    """

    def resolve(
        self,
        page,  # kept for signature compatibility; we generate selectors from text only
        target: str,
        action: str,
        locator_type: Optional[str] = None,
        value: Optional[str] = None,
    ) -> str:
        action = (action or "").lower().strip()
        locator_type = (locator_type or "").lower().strip() if locator_type else ""
        target = (target or "").strip()
        value = (value or "").strip() if value is not None else ""

        candidates: List[str] = []

        # 0) Anchor expression support: target = below/above/within text "X"
        # Use this when planner emits target like: below text "Enter the bypass code."
        m = _ANCHOR_RE.match(target)
        if m:
            direction = m.group(1).lower()
            anchor = m.group(2)

            # Anchor → input/select/combobox near it
            ax = _xpath_literal(anchor)

            if action in ("input", "select"):
                # Prefer the nearest input/textarea/select following anchor
                if direction in ("below", "within", "inside"):
                    candidates += _candidate_list(
                        f"xpath=(//*[normalize-space()={ax}])[1]/following::input[1]",
                        f"xpath=(//*[normalize-space()={ax}])[1]/following::textarea[1]",
                        f'xpath=(//*[normalize-space()={ax}])[1]/following::*[@role="combobox"][1]',
                        f"xpath=(//*[normalize-space()={ax}])[1]/following::select[1]",
                    )
                elif direction == "above":
                    candidates += _candidate_list(
                        f"xpath=(//*[normalize-space()={ax}])[1]/preceding::input[1]",
                        f"xpath=(//*[normalize-space()={ax}])[1]/preceding::textarea[1]",
                        f'xpath=(//*[normalize-space()={ax}])[1]/preceding::*[@role="combobox"][1]',
                        f"xpath=(//*[normalize-space()={ax}])[1]/preceding::select[1]",
                    )

            if action in ("click",):
                # Click nearest clickable following anchor
                if direction in ("below", "within", "inside"):
                    candidates += _candidate_list(
                        f"xpath=(//*[normalize-space()={ax}])[1]/following::a[1]",
                        f"xpath=(//*[normalize-space()={ax}])[1]/following::button[1]",
                    )
                elif direction == "above":
                    candidates += _candidate_list(
                        f"xpath=(//*[normalize-space()={ax}])[1]/preceding::a[1]",
                        f"xpath=(//*[normalize-space()={ax}])[1]/preceding::button[1]",
                    )

        # 1) Accessibility-first candidates by locator_type where possible
        # Map common locator_type to role
        role_map: Dict[str, str] = {
            "button": "button",
            "link": "link",
            "tab": "tab",
            "textbox": "textbox",
            "textarea": "textbox",  # Playwright uses textbox role for textarea too
            "combobox": "combobox",
            "dropdown": "combobox",  # many dropdowns are combobox/listbox
            "checkbox": "checkbox",
            "radiobutton": "radio",
            "radio": "radio",
            "menuitem": "menuitem",
            "listitem": "listitem",
            "row": "row",
        }

        if locator_type in role_map and target:
            candidates += _candidate_list(
                _role_selector(role_map[locator_type], target)
            )

        # Generic clickable by role/name (if locator_type unknown but action suggests click)
        if action == "click" and target:
            candidates += _candidate_list(
                _role_selector("button", target),
                _role_selector("link", target),
                _role_selector("tab", target),
                _role_selector("menuitem", target),
            )

        # 2) Label/placeholder candidates (inputs/combobox)
        if locator_type in ("textbox", "textarea", "combobox", "dropdown") and target:
            # Playwright selector engines: label=, placeholder=
            candidates += _candidate_list(
                f'label="{_esc_text_value(target)}"',
                f'placeholder="{_esc_text_value(target)}"',
                _css_attr("aria-label", target),
                _css_attr("name", target),
            )

        # 3) Stable attribute candidates (universal)
        if target:
            candidates += _candidate_list(
                _css_attr("data-testid", target),
                _css_attr("data-test-id", target),
                _css_attr("data-test", target),
                _css_attr("id", target),
                _css_attr("title", target),
                _css_attr("aria-label", target),
            )

        # 4) Text candidates (click/assert)
        # Use exact first, then loose
        if action in ("click", "assert") and target:
            candidates += _candidate_list(
                _pw_text_exact(target),
                _pw_text_loose(target),
            )

        # 5) When action is select, also include option candidates by value text
        # NOTE: Selection execution should open the control and then click option.
        # These candidates are for option rows/choices, used in overlay selection.
        if action == "select" and value:
            # Try roles commonly used for options
            candidates += _candidate_list(
                _role_selector("option", value),
                _role_selector("row", value),
                _role_selector("listitem", value),
                _role_selector("menuitem", value),
                _pw_text_loose(value),
                f'css=[role="row"]:has-text("{_esc_text_value(value)}")',
                f'css=[role="option"]:has-text("{_esc_text_value(value)}")',
            )

        # 6) Final fallback: XPath text contains (brittle but universal)
        if target and action in ("click", "assert"):
            xt = _xpath_literal(target)
            candidates += _candidate_list(
                f"xpath=//*[contains(normalize-space(.), {xt})][1]",
            )

        # Deduplicate while preserving order
        seen = set()
        uniq: List[str] = []
        for c in candidates:
            c = c.strip()
            if not c:
                continue
            if c in seen:
                continue
            seen.add(c)
            uniq.append(c)

        return "\n\n".join(uniq)
