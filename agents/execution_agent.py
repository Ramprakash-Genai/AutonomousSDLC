# agents/execution_agent.py
from __future__ import annotations

import json
import os
import time
import re
from typing import Any, Dict, Optional, List

from tools.playwright_runner import get_page
from tools.dom_extractor import get_dom
from tools.smart_locator import SmartLocatorResolver
from tools.interaction_engine import InteractionEngine

from agents.memory_store import MemoryStore, host_from_url, infer_locator_type
from agents.locator_agent import LocatorAgent
from agents.healing_agent import HealingAgent
from agents.auto_script_generator_agent import StepDefinitionGenerator


_SCOPE_RE = re.compile(
    r'(?P<child_type>text|tab|link|button)\s+"(?P<child>[^"]+)"\s+'
    r"(within|under|inside|from)\s+"
    r'(?P<scope_role>tablist|dialog|region|form|section|list|table)\s+"(?P<scope_name>[^"]+)"',
    re.IGNORECASE,
)

_SCOPE_RE2 = re.compile(
    r"click\s+(?:the\s+)?(?P<child>.+?)\s+text\s+under\s+(?P<scope_name>.+?)\s+from\s+"
    r"(?P<scope_role>tablist|dialog|region|form|section|list|table)",
    re.IGNORECASE,
)


class ExecutionAgent:
    """
    Universal Execution Orchestrator (SmartLocator + InteractionEngine + Agentic fallback)

    Supports:
    - Normal execution (pytest/behave context) via execute()
    - FastAPI-safe locator preview via preview_generate_locator_details()
    """

    def __init__(self):
        self.memory = MemoryStore()
        self.smart = SmartLocatorResolver()
        self.engine = InteractionEngine(self.smart)
        self.locator_agent = LocatorAgent()
        self.healer = HealingAgent()
        self.step_gen = StepDefinitionGenerator(out_dir="features/steps")

    # =========================================================
    # Normal execution path (unchanged)
    # =========================================================
    def execute(self, context, planned_step):
        if isinstance(planned_step, (tuple, list)) and planned_step:
            planned_step = planned_step[0]

        plan: Dict[str, Any] = (
            planned_step if isinstance(planned_step, dict) else json.loads(planned_step)
        )
        page = get_page(context)

        self._stabilize(page)

        action = (plan.get("action") or "").strip().lower()
        page_name = plan.get("page") or "_global"
        target = plan.get("target")
        value = plan.get("value")
        table = plan.get("table")

        raw_step = getattr(context, "raw_step", "") if context else ""
        if raw_step and not plan.get("scope"):
            scope = self._scope_from_raw(raw_step)
            if scope:
                plan["scope"] = scope

        try:
            if action and target:
                self.step_gen.upsert(page_name, action, target)
        except Exception:
            pass

        if action == "launch":
            url = os.getenv("APP_URL")
            if not url:
                raise RuntimeError("APP_URL not found in .env for launch step")
            page.goto(url)
            self._stabilize(page)
            return

        if action == "navigate":
            if not value:
                raise RuntimeError("navigate step requires value=url")
            page.goto(str(value))
            self._stabilize(page)
            return

        if action in ("input", "fill") and table and isinstance(table, list):
            if target and str(target).lower() == "credentials":
                for row in table:
                    field = (row.get("field") or "").strip()
                    val = row.get("value")
                    if field:
                        row_plan = {
                            "action": "input",
                            "locator_type": "textbox",
                            "target": field,
                            "value": val,
                            "page": page_name,
                            "scope": plan.get("scope"),
                        }
                        self._execute_with_fallbacks(context, page, page_name, row_plan)
                return

        self._execute_with_fallbacks(context, page, page_name, plan)

    # =========================================================
    # Preview / Discovery Mode (FastAPI-safe + stable)
    # =========================================================
    def preview_generate_locator_details(
        self,
        feature_text: str,
        planned_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Hybrid Locator Preview (Enterprise-safe, FastAPI-safe)

        - Opens application ONCE (preview browser)
        - Navigates only safe steps (launch/navigate)
        - Uses tolerant navigation waits + retries (Oracle Fusion SSO friendly)
        - If navigation fails, returns heuristic locator JSON so demo never breaks
        """

        if planned_steps is None:
            planned_steps = []
            for s in self._extract_steps_from_feature(feature_text or ""):
                planned_steps.append(self._plan_from_bdd_step(s))

        from tools.playwright_runner import get_preview_page

        pw, browser, context, page = get_preview_page()

        wait_until = os.getenv("PREVIEW_WAIT_UNTIL", "domcontentloaded").strip()

        def safe_goto(url: str) -> bool:
            """
            Returns True if navigation succeeded enough to extract DOM.
            Handles net::ERR_ABORTED by retrying with more tolerant wait modes.
            """
            if not url:
                return False
            try:
                page.goto(url, wait_until=wait_until)
                return True
            except Exception as e:
                msg = str(e)
                # Retry once for aborts / SSO redirects
                if "ERR_ABORTED" in msg or "net::ERR_ABORTED" in msg:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        return True
                    except Exception:
                        try:
                            # Most tolerant: only wait for commit
                            page.goto(url, wait_until="commit")
                            return True
                        except Exception:
                            return False
                return False

        try:
            # First stabilization
            try:
                self._stabilize(page)
            except Exception:
                pass

            # Pass 1: safe navigation only
            nav_ok = True
            for plan in planned_steps:
                if not isinstance(plan, dict):
                    continue
                action = (plan.get("action") or "").strip().lower()
                value = plan.get("value")

                if action == "launch":
                    nav_ok = safe_goto(os.getenv("APP_URL", "").strip()) and nav_ok
                    continue

                if action == "navigate":
                    nav_ok = safe_goto(str(value)) and nav_ok
                    continue

            # Pass 2: locator generation
            locator_records: List[Dict[str, Any]] = []

            for plan in planned_steps:
                if not isinstance(plan, dict):
                    continue

                action = (plan.get("action") or "").strip().lower()
                page_name = plan.get("page") or "_global"
                target = plan.get("target")
                locator_type = (plan.get("locator_type") or "").strip().lower()

                # Skip asserts in preview
                if action == "assert":
                    continue

                # Skip destructive clicks in preview (still generate locator)
                if action == "click" and target:
                    t = str(target).lower()
                    if any(
                        k in t
                        for k in (
                            "approve",
                            "submit",
                            "save",
                            "delete",
                            "remove",
                            "create",
                            "confirm",
                            "purchase",
                            "checkout",
                        )
                    ):
                        pass

                # If navigation succeeded, use DOM; else use empty DOM (heuristic locator)
                dom = self._safe_dom(page) if nav_ok else ""

                loc = self._try_locator_agent(dom, plan, getattr(page, "url", ""))

                # Fallback: healing agent suggestions
                if not loc:
                    try:
                        cands = (
                            self.healer.suggest_candidates(
                                dom=dom,
                                target=target,
                                action=action,
                                page_url=getattr(page, "url", ""),
                                locator_type=locator_type,
                                error="preview",
                            )
                            or []
                        )
                        loc = cands[0] if cands else None
                    except Exception:
                        loc = None

                # Final fallback: heuristic role/text (ensures JSON always returns)
                if not loc and target:
                    # very safe universal locator guess
                    loc = f'text="{target}"'

                host = host_from_url(getattr(page, "url", ""))
                if target and loc:
                    locator_records.append(
                        {
                            "page": page_name,
                            "host": host,
                            "action": action,
                            "target": target,
                            "locator": loc,
                            "locator_type": infer_locator_type(loc),
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        }
                    )

            return {
                "plans": planned_steps,
                "locator_details": locator_records,
                "preview_navigation_ok": nav_ok,
            }

        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    # ----------------------------
    # Deterministic BDD -> Plan (preview)
    # ----------------------------
    def _snake_case_page(self, page_name: str) -> str:
        p = (page_name or "").strip()
        if not p:
            return "_global"
        p = re.sub(r"\s+", "_", p)
        p = re.sub(r"[^a-zA-Z0-9_]+", "", p)
        p = p.lower()
        if not p.endswith("_page"):
            p = p + "_page"
        return p

    def _plan_from_bdd_step(self, step_line: str) -> Dict[str, Any]:
        s = (step_line or "").strip()
        for pref in ("Given ", "When ", "Then ", "And ", "But "):
            if s.startswith(pref):
                s = s[len(pref) :].strip()
                break

        page = None
        m_page = re.search(r"\s+in\s+(.+)$", s)
        if m_page:
            page_raw = m_page.group(1).strip()
            page = self._snake_case_page(page_raw)
            s = s[: m_page.start()].strip()

        m_nav = re.search(r'user\s+navigates\s+to\s+"([^"]+)"', s, re.IGNORECASE)
        if m_nav:
            return {
                "page": page,
                "action": "navigate",
                "locator_type": None,
                "target": None,
                "value": m_nav.group(1),
                "table": None,
            }

        m_click = re.search(r'user\s+clicks\s+(\w+)\s+"([^"]+)"', s, re.IGNORECASE)
        if m_click:
            lt = m_click.group(1).strip().lower()
            return {
                "page": page,
                "action": "click",
                "locator_type": lt,
                "target": m_click.group(2),
                "value": None,
                "table": None,
            }

        m_fill = re.search(
            r'user\s+fills\s+"([^"]+)"\s+into\s+(\w+)\s+"([^"]+)"', s, re.IGNORECASE
        )
        if m_fill:
            lt = m_fill.group(2).strip().lower()
            return {
                "page": page,
                "action": "input",
                "locator_type": lt,
                "target": m_fill.group(3),
                "value": m_fill.group(1),
                "table": None,
            }

        m_sel = re.search(
            r'user\s+selects\s+"([^"]+)"(?:\s+from\s+"([^"]+)"\s+(\w+))?',
            s,
            re.IGNORECASE,
        )
        if m_sel:
            option_val = m_sel.group(1)
            control = m_sel.group(2)
            lt = (m_sel.group(3) or "dropdown").strip().lower()
            return {
                "page": page,
                "action": "select",
                "locator_type": lt,
                "target": control or "first_visible",
                "value": option_val,
                "table": None,
            }

        m_assert = re.search(
            r'user\s+should\s+see\s+text\s+"([^"]+)"', s, re.IGNORECASE
        )
        if m_assert:
            return {
                "page": page,
                "action": "assert",
                "locator_type": "text",
                "target": m_assert.group(1),
                "value": "visible",
                "table": None,
            }

        return {
            "page": page,
            "action": None,
            "locator_type": None,
            "target": None,
            "value": None,
            "table": None,
        }

    def _extract_steps_from_feature(self, feature_text: str) -> List[str]:
        steps: List[str] = []
        for line in (feature_text or "").splitlines():
            l = line.strip()
            if l.lower().startswith(("given ", "when ", "then ", "and ", "but ")):
                steps.append(l)
        return steps

    # ----------------------------
    # Core fallbacks (execution)
    # ----------------------------
    def _execute_with_fallbacks(
        self, context, page, page_name: str, plan: Dict[str, Any]
    ):
        action = (plan.get("action") or "").strip().lower()
        target = plan.get("target")
        host = host_from_url(page.url)

        if target:
            cached = self.memory.get(page_name, host, action, target)
            locator = cached.get("locator") if cached else None
            if locator and self.engine.perform_with_selector(
                page, plan, locator, context=context
            ):
                self._record(context, plan, locator)
                return
            self.memory.invalidate(page_name, host, action, target)

        ok, used = self.engine.perform(page, plan, context=context)
        if ok:
            if used and target:
                self.memory.upsert(page_name, host, action, target, used)
            self._record(context, plan, used)
            return

        dom = self._safe_dom(page)
        llm_locator = self._try_locator_agent(dom, plan, page.url)
        if llm_locator:
            if self.engine.perform_with_selector(
                page, plan, llm_locator, context=context
            ):
                if target:
                    self.memory.upsert(page_name, host, action, target, llm_locator)
                self._record(context, plan, llm_locator)
                return

        self._heal(page, context, plan, dom)

    def _try_locator_agent(
        self, dom: str, plan: Dict[str, Any], page_url: str
    ) -> Optional[str]:
        try:
            return self.locator_agent.generate_locator(
                dom=dom,
                target=plan.get("target"),
                action=(plan.get("action") or "").strip().lower(),
                page_url=page_url,
                locator_type=(plan.get("locator_type") or "").strip().lower(),
            )
        except Exception:
            return None

    def _heal(self, page, context, plan: Dict[str, Any], dom: str):
        action = (plan.get("action") or "").strip().lower()
        target = plan.get("target") or "target"
        locator_type = (plan.get("locator_type") or "").strip().lower()

        ts = int(time.time())
        safe = str(target).replace(" ", "_").replace('"', "").replace(":", "_")[:80]

        try:
            page.screenshot(path=f"debug_fail_{safe}_{ts}.png", full_page=True)
        except Exception:
            pass

        if not dom:
            dom = self._safe_dom(page)

        try:
            with open(f"debug_dom_{safe}_{ts}.html", "w", encoding="utf-8") as f:
                f.write(dom or "")
        except Exception:
            pass

        try:
            candidates = (
                self.healer.suggest_candidates(
                    dom=dom,
                    target=plan.get("target"),
                    action=action,
                    page_url=page.url,
                    locator_type=locator_type,
                    error="action_failed",
                )
                or []
            )
        except Exception:
            candidates = []

        for cand in candidates:
            if not cand:
                continue
            if self.engine.perform_with_selector(page, plan, cand, context=context):
                host = host_from_url(page.url)
                if plan.get("target"):
                    self.memory.upsert(
                        plan.get("page") or "_global",
                        host,
                        action,
                        plan.get("target"),
                        cand,
                    )
                self._record(context, plan, cand)
                return

        raise RuntimeError(
            "Expected UI state not reached within timeout. "
            "The page may not have loaded or the expected section is not present."
        )

    def _stabilize(self, page):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    def _safe_dom(self, page) -> str:
        try:
            return get_dom(page) or ""
        except Exception:
            return ""

    def _record(self, context, plan: Dict[str, Any], locator: Optional[str]):
        try:
            rec = getattr(context, "recorder", None)
            if rec:
                rec.record_action(
                    action=plan.get("action"),
                    page_url=getattr(get_page(context), "url", ""),
                    page_name=plan.get("page") or "_global",
                    target=plan.get("target"),
                    locator=locator,
                    value=plan.get("value"),
                )
        except Exception:
            pass

    def _scope_from_raw(self, raw_step: str) -> Optional[Dict[str, str]]:
        s = (raw_step or "").strip()
        m = _SCOPE_RE.search(s)
        if m:
            return {
                "child_type": m.group("child_type"),
                "child": m.group("child"),
                "scope_role": m.group("scope_role"),
                "scope_name": m.group("scope_name"),
            }
        m2 = _SCOPE_RE2.search(s)
        if m2:
            return {
                "child_type": "text",
                "child": m2.group("child").strip(),
                "scope_role": m2.group("scope_role"),
                "scope_name": m2.group("scope_name").strip(),
            }
        return None
