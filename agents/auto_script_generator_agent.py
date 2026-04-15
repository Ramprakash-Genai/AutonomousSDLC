import os
import re
import importlib.util
from types import ModuleType
from typing import Optional


def safe_ident(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "step"


class StepDefinitionGenerator:
    """
    Generates and reuses page-wise helper step implementations:
      features/steps/<page>_definitions.py

    These are NOT Behave-decorated steps (to avoid conflicts with your catch-all step).
    They are helper functions you can reuse programmatically.
    """

    def __init__(self, out_dir: str = "features/steps"):
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    def file_path(self, page_name: str) -> str:
        page = safe_ident(page_name)
        return os.path.join(self.out_dir, f"{page}_definitions.py")

    def func_name(self, action: str, target: str) -> str:
        return f"{safe_ident(action)}__{safe_ident(target)}"

    def ensure_file(self, page_name: str):
        path = self.file_path(page_name)
        if os.path.exists(path):
            return
        header = [
            "# Auto-generated page helper step implementations (safe to commit)",
            "# NOTE: Not Behave-decorated. Used by generic_step runtime reuse.",
            "from __future__ import annotations",
            "",
            "def run_planned(executor, context, planned_json: str):",
            "    executor.execute(context, planned_json)",
            "",
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(header))

    def exists(self, page_name: str, action: str, target: str) -> bool:
        path = self.file_path(page_name)
        if not os.path.exists(path):
            return False
        fn = self.func_name(action, target)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return re.search(rf"^def\s+{re.escape(fn)}\s*\(", content, flags=re.M) is not None

    def upsert(self, page_name: str, action: str, target: str) -> str:
        self.ensure_file(page_name)
        path = self.file_path(page_name)
        fn = self.func_name(action, target)

        if self.exists(page_name, action, target):
            return fn

        lines = [
            "",
            f"def {fn}(executor, context, planned_json: str):",
            f"    \"\"\"Auto-generated helper for page={page_name}, action={action}, target={target}\"\"\"",
            "    return run_planned(executor, context, planned_json)",
            "",
        ]
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return fn

    def load_module(self, page_name: str) -> Optional[ModuleType]:
        path = self.file_path(page_name)
        if not os.path.exists(path):
            return None
        module_name = f"_autogen_{safe_ident(page_name)}_definitions"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod