# agents/locator_agent.py
from __future__ import annotations

from typing import Optional


class LocatorAgent:
    """
    LocatorAgent is responsible ONLY for generating locator candidates
    using DOM context + step intent.

    IMPORTANT:
    - This agent is stateless.
    - It does NOT persist any locator.
    - It does NOT execute UI interactions.
    - It can be safely used in BOTH:
        1) Preview / discovery mode
        2) Execution fallback mode
    """

    def __init__(self):
        pass

    def generate_locator(
        self,
        dom: str,
        target: Optional[str],
        action: Optional[str],
        page_url: str,
        locator_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generates a best-effort locator for a given UI target.

        Parameters
        ----------
        dom : str
            Full DOM snapshot (HTML) of the current page.
        target : str
            User-facing control name (e.g. "Item Description", "Approve").
        action : str
            Action intent (click, input, select, assert).
        page_url : str
            Current page URL (used for context if needed).
        locator_type : str, optional
            Preferred locator type (textbox, button, link, etc.).

        Returns
        -------
        Optional[str]
            Locator string (Playwright-compatible), or None if not found.
        """

        # Defensive checks
        if not dom:
            return None
        if not target:
            return None

        action = (action or "").strip().lower()
        locator_type = (locator_type or "").strip().lower()
        target_text = str(target).strip()

        # ------------------------------------------------------------------
        # Strategy 1: Role-based locators (preferred, stable)
        # ------------------------------------------------------------------
        # These are Playwright-friendly and resilient.
        # Example: role=textbox[name="Item Description"]

        role = None
        if locator_type in ("textbox", "input", "inputbox", "textarea"):
            role = "textbox"
        elif locator_type in ("button",):
            role = "button"
        elif locator_type in ("link",):
            role = "link"
        elif locator_type in ("tab",):
            role = "tab"

        if role:
            return f'role={role}[name="{target_text}"]'

        # ------------------------------------------------------------------
        # Strategy 2: Text-based fallback
        # ------------------------------------------------------------------
        # Example: text="Approve"

        return f'text="{target_text}"'
