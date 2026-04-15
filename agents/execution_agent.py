import json
import os
import time
import re

from tools.playwright_runner import get_page
from tools.dom_extractor import get_dom
from tools.smart_locator import SmartLocatorResolver
from agents.memory_store import MemoryStore, host_from_url
from agents.locator_agent import LocatorAgent
from agents.healing_agent import HealingAgent
from agents.auto_script_generator_agent import StepDefinitionGenerator


_SCROLL_HINT_RE = re.compile(r"scroll\s*=\s*(down|up)", re.IGNORECASE)

_ANCHOR_TARGET_RE = re.compile(
    r'^(?P<direction>below|above|within|inside)\s+text\s+"(?P<anchor>[^"]+)"',
    re.IGNORECASE,
)

_GRID_ROW_VALIDATE_RE = re.compile(
    r'^user\s+should\s+validate\s+the\s+grid\s+row\s+where\s+"(?P<keycol>[^"]+)"\s+is\s+"(?P<keyval>[^"]+)"',
    re.IGNORECASE,
)


# Universal scope pattern: clicks <child_type> "X" within/under/inside/from <scope_role> "Y"
_SCOPE_RE = re.compile(
    r"(?P<child_type>text|tab|link|button)\s+\"(?P<child>[^\"]+)\"\s+"
    r"(within|under|inside|from)\s+(?P<scope_role>tablist|dialog|region|form|section|list|table)\s+\"(?P<scope_name>[^\"]+)\"",
    re.IGNORECASE,
)


def _safe_xpath_literal(text: str) -> str:
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


class ExecutionAgent:
    def __init__(self):
        self.memory = MemoryStore()
        self.locator_agent = LocatorAgent()
        self.healer = HealingAgent()
        self.smart = SmartLocatorResolver()
        self.step_gen = StepDefinitionGenerator(out_dir="features/steps")

    def execute(self, context, planned_step):
        if isinstance(planned_step, (tuple, list)) and planned_step:
            planned_step = planned_step[0]

        data = (
            planned_step if isinstance(planned_step, dict) else json.loads(planned_step)
        )

        page = get_page(context)
        action = data.get("action")
        page_name = data.get("page") or "_global"
        target = data.get("target")
        value = data.get("value")
        table = data.get("table")
        locator_type = data.get("locator_type")

        self._stabilize(page)

        if action == "browser":
            return

        if action == "launch":
            url = os.getenv("APP_URL")
            if not url:
                raise RuntimeError("APP_URL not found in .env for launch step")
            page.goto(url)
            self._stabilize(page)
            self._record(context, "launch", page.url, page_name)
            return

        if action == "navigate":
            if not value:
                raise RuntimeError("navigate step requires value=url")
            page.goto(value)
            self._stabilize(page)
            self._record(context, "navigate", page.url, page_name)
            return

        # table-driven credentials input (existing behavior)
        if action == "input" and table and isinstance(table, list):
            if target and str(target).lower() == "credentials":
                for row in table:
                    field = (row.get("field") or "").strip()
                    val = row.get("value")
                    if field:
                        self._execute_single_action(
                            context,
                            page,
                            page_name,
                            "input",
                            field,
                            val,
                            locator_type="textbox",
                            table=None,
                        )
                return

        self._execute_single_action(
            context,
            page,
            page_name,
            action,
            target,
            value,
            locator_type=locator_type,
            table=table,
        )

    def _time_left_ms(self, context, default_ms: int = 60000) -> int:
        deadline = getattr(context, "step_deadline", None)
        if not deadline:
            return default_ms
        left = int((deadline - time.monotonic()) * 1000)
        return max(0, left)

    def _try_click_control_by_role(
        self, page, target: str, locator_type: str, context=None
    ) -> bool:
        """Deterministic open for combobox/dropdown using semantic role APIs."""
        if not target:
            return False

        timeout_ms = (
            min(60000, self._time_left_ms(context, 60000)) if context else 60000
        )
        if timeout_ms <= 0:
            return False

        name = str(target)
        lt = (locator_type or "").lower()

        if lt == "combobox":
            try:
                cb = page.get_by_role("combobox", name=name, exact=False).first
                cb.wait_for(state="visible", timeout=timeout_ms)
                cb.click()
                return True
            except Exception:
                return False

        if lt == "dropdown":
            try:
                btn = page.get_by_role("button", name=name, exact=False).first
                btn.wait_for(state="visible", timeout=timeout_ms)
                btn.click()
                return True
            except Exception:
                pass
            try:
                cb = page.get_by_role("combobox", name=name, exact=False).first
                cb.wait_for(state="visible", timeout=timeout_ms)
                cb.click()
                return True
            except Exception:
                return False

        return False

    def _try_fill_combobox(
        self, page, control_name: str, value: str, context=None
    ) -> bool:
        """Universal combobox fill/select helper for enterprise typeahead comboboxes."""
        if not control_name or value is None:
            return False

        timeout_ms = (
            min(60000, self._time_left_ms(context, 60000)) if context else 60000
        )
        if timeout_ms <= 0:
            return False

        name = str(control_name)
        val = str(value)

        cb = None
        try:
            cb = page.get_by_role("combobox", name=name, exact=False).first
            cb.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            cb = None

        if cb is None:
            # fallback aria-label combobox input
            try:
                cb = page.locator(f'input[role="combobox"][aria-label="{name}"]').first
                cb.wait_for(state="visible", timeout=timeout_ms)
            except Exception:
                return False

        try:
            try:
                cb.scroll_into_view_if_needed()
            except Exception:
                pass
            cb.click()
        except Exception:
            return False

        # type/fill
        try:
            cb.fill(val)
        except Exception:
            try:
                cb.type(val, delay=30)
            except Exception:
                return False

        # try option click
        try:
            opt = page.get_by_role("option", name=val, exact=True).first
            if opt.count() > 0:
                opt.click()
                return True
        except Exception:
            pass

        try:
            opt = page.get_by_text(val, exact=True).first
            if opt.count() > 0:
                opt.click()
                return True
        except Exception:
            pass

        # last resort: Enter
        try:
            cb.press("Enter")
        except Exception:
            pass

        # verify
        try:
            current = cb.input_value()
            if current and val.lower() in current.lower():
                return True
        except Exception:
            pass

        try:
            t = cb.text_content() or ""
            if val.lower() in t.lower():
                return True
        except Exception:
            pass

        return False

    def _try_scoped_action(
        self, page, raw_step: str, action: str, value, context=None
    ) -> bool:
        """Universal scoped execution.

        If a step contains scope intent like:
          clicks <child_type> "X" within/under/inside/from <scope_role> "Y"
        this method will find the scope container and perform the action inside it.

        This prevents duplicate-text clicks and makes interaction universal across applications.
        """
        if not raw_step:
            return False

        m = _SCOPE_RE.search(raw_step)
        if not m:
            return False

        child_type = (m.group("child_type") or "text").lower()
        child = m.group("child")
        scope_role = (m.group("scope_role") or "").lower()
        scope_name = m.group("scope_name")

        timeout_ms = 60000
        if context is not None:
            timeout_ms = min(timeout_ms, self._time_left_ms(context, 60000))
            if timeout_ms <= 0:
                return False

        try:
            scope = page.get_by_role(scope_role, name=scope_name, exact=False).first
            scope.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return False

        try:
            if action == "click":
                if child_type == "tab":
                    el = scope.get_by_role("tab", name=child, exact=False).first
                elif child_type == "link":
                    el = scope.get_by_role("link", name=child, exact=False).first
                elif child_type == "button":
                    el = scope.get_by_role("button", name=child, exact=False).first
                else:
                    el = scope.get_by_text(child, exact=False).first

                el.wait_for(state="visible", timeout=timeout_ms)
                el.click()
                return True

            if action == "assert":
                el = scope.get_by_text(child, exact=False).first
                el.wait_for(state="visible", timeout=timeout_ms)
                return True

            if action == "input":
                # For scoped input, interpret child as label within the scope
                inp = scope.get_by_label(child, exact=False).first
                inp.wait_for(state="visible", timeout=timeout_ms)
                inp.fill(str(value or ""))
                return True

            return False
        except Exception:
            return False

    def _execute_single_action(
        self,
        context,
        page,
        page_name,
        action,
        target,
        value,
        locator_type=None,
        table=None,
    ):
        if action in ("input", "click", "assert", "select") and not target:
            raise RuntimeError(f"{action} requires target but got: {target}")

        host = host_from_url(page.url)

        # artifact generation (existing behavior)
        try:
            if action in ("input", "click", "assert", "select") and target:
                self.step_gen.upsert(page_name, action, target)
        except Exception:
            pass

        # ✅ Universal combobox/dropdown click open (before memory/smart/LLM)
        if action == "click" and (locator_type or "").lower() in (
            "combobox",
            "dropdown",
        ):
            if self._try_click_control_by_role(
                page, str(target), str(locator_type), context=context
            ):
                self._record(
                    context,
                    action,
                    page.url,
                    page_name,
                    target,
                    locator=f"role_click:{locator_type}:{target}",
                    value=value,
                )
                return

        # ✅ Universal combobox/dropdown input handling (before memory/smart/LLM)
        if action == "input" and (locator_type or "").lower() in (
            "combobox",
            "dropdown",
        ):
            if self._try_fill_combobox(
                page, str(target), str(value or ""), context=context
            ):
                self._record(
                    context,
                    action,
                    page.url,
                    page_name,
                    target,
                    locator=f"combobox_fill:{target}",
                    value=value,
                )
                return

        # 1) Memory
        mem = self.memory.get(page_name, host, action, target)
        if mem:
            locator = mem["locator"]
            if self._try_action(page, action, locator, value, context=context):
                self._record(
                    context, action, page.url, page_name, target, locator, value
                )
                return
            self.memory.invalidate(page_name, host, action, target)

        # 2) Smart resolver (universal policy)
        smart_loc = self.smart.resolve(page, target, action, locator_type=locator_type)
        if smart_loc and self._try_action(
            page, action, smart_loc, value, context=context
        ):
            self.memory.upsert(page_name, host, action, target, smart_loc)
            self._record(context, action, page.url, page_name, target, smart_loc, value)
            return

        # 3) LocatorAgent (BlueVerse) – only when deterministic fails
        dom = get_dom(page)
        llm_loc = self.locator_agent.generate_locator(
            dom, target, action, page.url, locator_type=locator_type
        )
        if llm_loc and self._try_action(page, action, llm_loc, value, context=context):
            self.memory.upsert(page_name, host, action, target, llm_loc)
            self._record(context, action, page.url, page_name, target, llm_loc, value)
            return

        # 4) Healing
        self._heal(
            page,
            context,
            page_name,
            host,
            action,
            target,
            value,
            locator_type=locator_type,
        )

    def _heal(
        self, page, context, page_name, host, action, target, value, locator_type=None
    ):
        wait_ms = min(60000, self._time_left_ms(context, 60000))
        if wait_ms > 0:
            first = max(1000, wait_ms // 2)
            second = max(1000, wait_ms - first)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=first)
            except Exception:
                pass
            remaining = min(second, self._time_left_ms(context, second))
            if remaining > 0:
                try:
                    page.wait_for_load_state("networkidle", timeout=remaining)
                except Exception:
                    pass

        if self._time_left_ms(context, 1) <= 0:
            raise RuntimeError(
                "Expected UI state not reached within 60 seconds. "
                "The page may not have loaded or the expected section is not present. "
                "Please verify network/load state and the target anchor text."
            )

        ts = int(time.time())
        safe_name = (
            str(target).replace(" ", "_").replace('"', "").replace(":", "_")[:80]
        )
        try:
            page.screenshot(path=f"debug_fail_{safe_name}_{ts}.png", full_page=True)
        except Exception:
            pass

        dom = ""
        try:
            dom = get_dom(page)
            with open(f"debug_dom_{safe_name}_{ts}.html", "w", encoding="utf-8") as f:
                f.write(dom)
        except Exception:
            pass

        candidates = self.healer.suggest_candidates(
            dom=dom,
            target=target,
            action=action,
            page_url=page.url,
            locator_type=locator_type,
            error="action_failed",
        )

        for cand in candidates:
            if self._time_left_ms(context, 1) <= 0:
                break
            if self._try_action(page, action, cand, value, context=context):
                self.memory.upsert(page_name, host, action, target, cand)
                self._record(context, action, page.url, page_name, target, cand, value)
                return

        raise RuntimeError(
            "Expected UI state not reached within 60 seconds. "
            "The page may not have loaded or the expected section is not present. "
            "Please verify network/load state and the target anchor text."
        )

    def _stabilize(self, page):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass

    def _try_action(self, page, action, locator, value, context=None):
        locator = (locator or "").strip()
        if not locator:
            return False

        # multi-candidate support
        if "\n\n" in locator:
            parts = [p.strip() for p in locator.split("\n\n") if p.strip()]
            for part in parts:
                if self._try_action(page, action, part, value, context=context):
                    return True
            return False

        timeout_ms = 60000
        if context is not None:
            timeout_ms = min(timeout_ms, self._time_left_ms(context, 60000))
            if timeout_ms <= 0:
                return False

        if self._try_on_context(page, action, locator, value, timeout_ms):
            return True

        try:
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                if self._try_on_context(frame, action, locator, value, timeout_ms):
                    return True
        except Exception:
            pass

        return False

    def _try_on_context(self, ctx, action, locator, value, timeout_ms):
        try:
            loc = ctx.locator(locator)
            if action == "input":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.fill(str(value or ""))
                return True
            if action == "click":
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.click()
                return True
            if action == "assert":
                loc.wait_for(state="visible", timeout=timeout_ms)
                return loc.is_visible()
            if action == "select":
                loc.wait_for(state="visible", timeout=timeout_ms)
                try:
                    loc.select_option(str(value))
                    return True
                except Exception:
                    pass

                # fallback for custom selects
                try:
                    loc.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    loc.click()
                except Exception:
                    return False

                opt_text = str(value or "").strip()
                if not opt_text:
                    return False

                try:
                    opt = ctx.get_by_role("option", name=opt_text, exact=True).first
                    if opt.count() > 0:
                        opt.click()
                        return True
                except Exception:
                    pass

                try:
                    opt = ctx.get_by_text(opt_text, exact=True).first
                    if opt.count() > 0:
                        opt.click()
                        return True
                except Exception:
                    pass

                try:
                    loc.fill(opt_text)
                    loc.press("Enter")
                    return True
                except Exception:
                    return False

            return False
        except Exception:
            return False

    def _record(
        self,
        context,
        action,
        page_url,
        page_name,
        target=None,
        locator=None,
        value=None,
    ):
        if hasattr(context, "recorder") and context.recorder:
            context.recorder.record(
                action=action,
                page_url=page_url,
                page_name=page_name,
                target=target,
                locator=locator,
                value=value,
            )
