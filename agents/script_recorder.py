import os
import re
import json
from dataclasses import dataclass
from typing import List, Optional


def _normalize_test_suffix(name: str) -> str:
    """
    Normalizes pytest node/scenario names into a stable test suffix.
    Example:
      'test_valid_login' -> 'valid_login'
      'Valid Login'      -> 'valid_login'
    """
    name = (name or "scenario").strip()

    # Avoid double 'test_test_' in output
    if name.lower().startswith("test_"):
        name = name[5:]

    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "scenario"


def _contains_test_function(file_text: str, fn_name: str) -> bool:
    """
    Returns True if file contains: def <fn_name>(
    """
    pattern = rf"^\s*def\s+{re.escape(fn_name)}\s*\("
    return re.search(pattern, file_text or "", flags=re.MULTILINE) is not None


@dataclass
class RecordedAction:
    action: str
    page_url: str
    page_name: str
    target: Optional[str]
    locator: Optional[str]
    value: Optional[str]  # may be masked


class ScriptRecorder:
    """
    Generates pytest-playwright scripts as an artifact from what actually ran.

    New behavior (as requested):
    - Uses stable naming:
        file:   generated_tests/test_<scenario>.py
        method: def test_<scenario>()
    - Reuse existing file/method if already present (default).
    - Overwrite the file only when 'force_overwrite=True' (e.g., scenario failed).
    """

    def __init__(self, out_dir="generated_tests", mask_secrets=True):
        self.out_dir = out_dir
        self.mask_secrets = mask_secrets
        os.makedirs(self.out_dir, exist_ok=True)
        self.actions: List[RecordedAction] = []
        self.scenario_name = "scenario"

    def start_scenario(self, scenario_name: str):
        self.scenario_name = scenario_name or "scenario"
        self.actions = []

    def _mask(self, target: str, value: str) -> str:
        if not self.mask_secrets:
            return value
        if target and any(k in target.lower() for k in ("password", "pwd", "secret", "token")):
            return "******"
        return value

    def record(
        self,
        *,
        action: str,
        page_url: str,
        page_name: str,
        target=None,
        locator=None,
        value=None,
    ):
        if value is not None and target is not None:
            value = self._mask(target, str(value))
        self.actions.append(RecordedAction(action, page_url, page_name, target, locator, value))

    def write_pytest(self, force_overwrite: bool = False) -> str:
        """
        Writes/updates the generated test script.

        - If file exists AND contains the expected test function:
            - If force_overwrite=False -> DO NOTHING (reuse existing)
            - If force_overwrite=True  -> OVERWRITE (replace with newly recorded actions)
        - If file does not exist OR function does not exist -> WRITE new file.
        """
        suffix = _normalize_test_suffix(self.scenario_name)
        file_name = f"test_{suffix}.py"
        fn_name = f"test_{suffix}"

        path = os.path.join(self.out_dir, file_name)

        if os.path.exists(path):
            try:
                existing = open(path, "r", encoding="utf-8").read()
            except Exception:
                existing = ""

            has_fn = _contains_test_function(existing, fn_name)

            # Reuse mode: keep existing test if present and no overwrite requested
            if has_fn and not force_overwrite:
                return path

        # Otherwise create/overwrite with what actually ran
        lines = []
        lines.append("from playwright.sync_api import sync_playwright")
        lines.append("")
        lines.append(f"def {fn_name}():")
        lines.append("    with sync_playwright() as p:")
        lines.append("        browser = p.chromium.launch(headless=False)")
        lines.append("        context = browser.new_context()")
        lines.append("        page = context.new_page()")
        lines.append("")

        for a in self.actions:
            if a.action in ("navigate", "launch"):
                lines.append(f"        page.goto({json.dumps(a.page_url)})")
            elif a.action == "input" and a.locator:
                lines.append(
                    f"        page.locator({json.dumps(a.locator)}).fill({json.dumps(a.value or '')})"
                )
            elif a.action == "click" and a.locator:
                lines.append(f"        page.locator({json.dumps(a.locator)}).click()")
            elif a.action == "assert" and a.locator:
                lines.append(f"        assert page.locator({json.dumps(a.locator)}).is_visible()")

        lines.append("")
        lines.append("        context.close()")
        lines.append("        browser.close()")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return path