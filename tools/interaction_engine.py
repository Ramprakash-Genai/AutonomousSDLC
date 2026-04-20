# tools/interaction_engine.py
# Universal interaction engine for Playwright-based automation (non-hardcoded)
# Key capability: normalize plan DSL + robust universal text assertions.

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple


class InteractionEngine:
    """
    Requires smart_locator:
      resolve(page, target, action, locator_type=None, value=None) -> str
    returning candidates separated by '\\n\\n'
    """

    def __init__(self, smart_locator):
        self.smart = smart_locator

        # Universal DSL aliases (NOT app-specific)
        self._ALIASES = {
            "fill": "input",
            "enter": "input",
            "type_into": "input",
            "validate": "assert",
            "should_see": "assert",
            "verify": "assert",
        }

    # ---------------------------------------------------------------------
    # Normalization (universal DSL protocol)
    # ---------------------------------------------------------------------
    def normalize_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert planner outputs into canonical actions supported by engine.
        This is NOT hardcoding. It is universal DSL normalization.
        """
        if not isinstance(plan, dict):
            return plan

        p = dict(plan)
        action = (p.get("action") or "").strip().lower()
        locator_type = (p.get("locator_type") or "").strip().lower()

        # normalize aliases
        action = self._ALIASES.get(action, action)

        # normalize assert
        if action == "assert":
            # If planner says locator_type=text, treat as contains text assertion
            if locator_type in ("text", "label", "content"):
                p["action"] = "assert_text_contains"
                if not p.get("match"):
                    p["match"] = {"mode": "contains", "text": p.get("target", "")}
            else:
                # default for non-text asserts: visible
                p["action"] = "assert_visible"

        else:
            p["action"] = action

        return p

    # ---------------------------------------------------------------------
    # Public APIs
    # ---------------------------------------------------------------------
    def perform(
        self, page, plan: Dict[str, Any], context=None
    ) -> Tuple[bool, Optional[str]]:
        """
        Executes plan using ranked candidates from SmartLocatorResolver.
        Returns: (ok, used_selector) where used_selector is the element selector used (if applicable).
        """
        plan = self.normalize_plan(plan)
        action = (plan.get("action") or "").strip().lower()
        if not action:
            return False, None

        ctx = self._apply_scope(page, plan.get("scope"))
        timeout_ms = self._timeout_ms(context, 60000)

        # ✅ Universal text assertions do NOT need SmartLocator candidates
        if action == "assert_text_contains":
            ok = self._assert_text_contains(page, plan, timeout_ms)
            return (ok, "page.get_by_text(exact=False)") if ok else (False, None)

        if action == "assert_text_equals":
            ok = self._assert_text_equals(page, plan, timeout_ms)
            return (ok, "page.get_by_text(exact=True)") if ok else (False, None)

        if (
            action == "assert_visible"
            and (plan.get("locator_type") or "").strip().lower() == "text"
        ):
            ok = self._assert_text_contains(page, plan, timeout_ms)
            return (ok, "page.get_by_text(exact=False)") if ok else (False, None)

        # select is special
        if action == "select":
            ok, used = self._select(ctx, page, plan, timeout_ms)
            return ok, used

        # Otherwise resolve candidates for target and try them
        target = str(plan.get("target") or "").strip()
        locator_type = str(plan.get("locator_type") or "").strip().lower()
        value = plan.get("value")

        cand_str = self.smart.resolve(
            page, target, action, locator_type=locator_type, value=value
        )
        candidates = [c.strip() for c in cand_str.split("\n\n") if c.strip()]

        for selector in candidates:
            if self.perform_with_selector(
                page, plan, selector, context=context, ctx_override=ctx
            ):
                return True, selector

        return False, None

    def perform_with_selector(
        self,
        page,
        plan: Dict[str, Any],
        selector: str,
        context=None,
        ctx_override=None,
    ) -> bool:
        """
        Execute plan with explicit selector (memory / locator agent / healer candidate).
        """
        plan = self.normalize_plan(plan)
        action = (plan.get("action") or "").strip().lower()
        selector = (selector or "").strip()
        if not action or not selector:
            return False

        ctx = (
            ctx_override
            if ctx_override is not None
            else self._apply_scope(page, plan.get("scope"))
        )
        timeout_ms = self._timeout_ms(context, 60000)
        value = plan.get("value")

        try:
            loc = ctx.locator(selector).first
        except Exception:
            return False

        try:
            if action == "click":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.click()
                return True

            if action == "double_click":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.dblclick()
                return True

            if action == "right_click":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.click(button="right")
                return True

            if action == "hover":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.hover()
                return True

            if action in ("input", "fill"):
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.fill("" if value is None else str(value))
                return True

            if action == "type":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.type("" if value is None else str(value))
                return True

            if action == "clear":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.fill("")
                return True

            if action == "press":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.press("" if value is None else str(value))
                return True

            if action == "check":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.check()
                return True

            if action == "uncheck":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.uncheck()
                return True

            if action in ("choose", "radio"):
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.check()
                return True

            if action == "assert_visible":
                loc.wait_for(state="visible", timeout=timeout_ms)
                return bool(loc.is_visible())

            if action == "assert_not_visible":
                try:
                    loc.wait_for(state="visible", timeout=1500)
                    return False
                except Exception:
                    return True

            if action == "assert_text_contains":
                expected = self._match_text(plan) or ""
                loc.wait_for(state="visible", timeout=timeout_ms)
                try:
                    txt = loc.inner_text() or ""
                except Exception:
                    txt = loc.text_content() or ""
                return expected.lower() in txt.lower()

            if action == "assert_text_equals":
                expected = (self._match_text(plan) or "").strip()
                loc.wait_for(state="visible", timeout=timeout_ms)
                try:
                    txt = (loc.inner_text() or "").strip()
                except Exception:
                    txt = (loc.text_content() or "").strip()
                return txt == expected

            if action == "assert_value":
                expected = "" if value is None else str(value)
                loc.wait_for(state="visible", timeout=timeout_ms)
                try:
                    actual = loc.input_value()
                except Exception:
                    actual = (loc.text_content() or "").strip()
                return (actual or "").strip() == expected.strip()

            if action == "scroll_into_view":
                loc.scroll_into_view_if_needed()
                return True

            if action == "upload_file":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.set_input_files(value)
                return True

            if action == "wait_for":
                state = str(plan.get("value") or "networkidle")
                try:
                    page.wait_for_load_state(state, timeout=timeout_ms)
                    return True
                except Exception:
                    return False

            if action == "navigate":
                url = str(plan.get("value") or "").strip()
                if not url:
                    return False
                page.goto(url)
                return True

        except Exception:
            return False

        return False

    # ---------------------------------------------------------------------
    # Scope
    # ---------------------------------------------------------------------
    def _apply_scope(self, page, scope: Optional[Dict[str, Any]]):
        if not scope:
            return page
        try:
            role = (scope.get("role") or "").strip().lower()
            name = (scope.get("name") or "").strip()
            if role and name:
                return page.get_by_role(role, name=name, exact=False)
        except Exception:
            pass
        return page

    # ---------------------------------------------------------------------
    # Universal assertions (page-level)
    # ---------------------------------------------------------------------
    def _assert_text_contains(
        self, page, plan: Dict[str, Any], timeout_ms: int
    ) -> bool:
        text = self._match_text(plan) or ""
        text = text.strip()
        if not text:
            return False
        try:
            loc = page.get_by_text(text, exact=False).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    def _assert_text_equals(self, page, plan: Dict[str, Any], timeout_ms: int) -> bool:
        text = self._match_text(plan) or ""
        text = text.strip()
        if not text:
            return False
        try:
            loc = page.get_by_text(text, exact=True).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------------
    # Select primitive (overlay list supports role=row)
    # ---------------------------------------------------------------------
    def _select(
        self, ctx, page, plan: Dict[str, Any], timeout_ms: int
    ) -> Tuple[bool, Optional[str]]:
        target = str(plan.get("target") or "").strip()
        value = str(plan.get("value") or "").strip()
        locator_type = (plan.get("locator_type") or "combobox").strip().lower()
        if not target or not value:
            return False, None

        control_cands_str = self.smart.resolve(
            page, target, "click", locator_type=locator_type, value=""
        )
        control_cands = [
            c.strip() for c in control_cands_str.split("\n\n") if c.strip()
        ]

        for ctrl_sel in control_cands:
            try:
                ctrl = ctx.locator(ctrl_sel).first
                if ctrl.count() == 0:
                    continue

                ctrl.wait_for(state="visible", timeout=timeout_ms)

                # native <select>
                try:
                    ctrl.select_option(value)
                    return True, ctrl_sel
                except Exception:
                    pass

                # open overlay
                try:
                    ctrl.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:
                    ctrl.click()
                except Exception:
                    continue

                if self._pick_option(page, value, timeout_ms):
                    return True, ctrl_sel

                # typeahead fallback
                try:
                    ctrl.fill(value)
                    ctrl.press("Enter")
                    return True, ctrl_sel
                except Exception:
                    pass

            except Exception:
                continue

        return False, None

    def _pick_option(self, page, value_text: str, timeout_ms: int) -> bool:
        v = (value_text or "").strip()
        if not v:
            return False

        try:
            page.wait_for_timeout(150)
        except Exception:
            pass

        for role in ["option", "row", "menuitem", "listitem"]:
            try:
                opt = page.get_by_role(role, name=v, exact=False).first
                if opt.count() > 0:
                    opt.wait_for(state="visible", timeout=timeout_ms)
                    opt.click()
                    return True
            except Exception:
                pass

        try:
            opt = page.get_by_text(v, exact=False).first
            if opt.count() > 0:
                opt.wait_for(state="visible", timeout=timeout_ms)
                opt.click()
                return True
        except Exception:
            pass

        try:
            opt = page.locator(f'[role="row"]:has-text("{self._esc(v)}")').first
            if opt.count() > 0:
                opt.wait_for(state="visible", timeout=timeout_ms)
                opt.click()
                return True
        except Exception:
            pass

        return False

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _timeout_ms(self, context, default_ms: int) -> int:
        deadline = getattr(context, "step_deadline", None)
        if not deadline:
            return default_ms
        left = int((deadline - time.monotonic()) * 1000)
        return max(1000, min(default_ms, left))

    def _match_text(self, plan: Dict[str, Any]) -> Optional[str]:
        m = plan.get("match") or {}
        return m.get("text") or plan.get("target")

    def _esc(self, s: str) -> str:
        return (
            (s or "").replace('"', '\\"').replace("\n", " ").replace("\r", " ").strip()
        )
