import re
from dataclasses import dataclass
from typing import Optional

from agents.config import BlueVerseConfig, BlueVerseClient


@dataclass
class RefinerConfig:
    use_llm: bool = True  # means "use BlueVerse agent"
    max_tokens: int = 3000  # unused, kept for compatibility


_GHERKIN_HEADER_RE = re.compile(r"^\s*(Feature:|Background:|Scenario:|Scenario Outline:|Examples:)\b")
_GHERKIN_STEP_RE = re.compile(r"^\s*(Given|When|Then|And|But)\b")
_TAG_RE = re.compile(r"^\s*@")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_DOCSTRING_RE = re.compile(r'^\s*"""')


def _first_meaningful_line(text: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s
    return ""


def _looks_like_valid_gherkin(text: str) -> bool:
    first = _first_meaningful_line(text)
    if not first:
        return False
    if first.startswith("Feature:"):
        return True
    if first.startswith("#") and "language" in first.lower():
        return True
    return False


class FeatureRefinerAgent:
    def __init__(self, config: Optional[RefinerConfig] = None):
        self.config = config or RefinerConfig()
        self._bv = BlueVerseClient(BlueVerseConfig.from_env())

    def refine(self, raw_feature_text: str) -> str:
        deterministic = self._deterministic_normalize(raw_feature_text)

        if self.config.use_llm:
            try:
                refined = self._bv.refine_feature(deterministic)
                if _looks_like_valid_gherkin(refined) and "Given Feature:" not in refined:
                    return refined
            except Exception:
                pass

        return deterministic

    def _deterministic_normalize(self, text: str) -> str:
        text = (text or "").replace("\r\n", "\n")

        if not re.search(r"^\s*Feature:", text, flags=re.MULTILINE):
            text = "Feature: Refined Feature\n\n" + text

        lines = text.split("\n")
        refined = []
        in_docstring = False
        inside_block = False
        last_step_prefix = None

        for line in lines:
            stripped = line.strip()

            if _DOCSTRING_RE.match(stripped):
                refined.append(line)
                in_docstring = not in_docstring
                continue
            if in_docstring:
                refined.append(line)
                continue

            if not stripped or stripped.startswith("#"):
                refined.append(line)
                continue

            if _TAG_RE.match(stripped):
                refined.append(line)
                continue

            if _TABLE_ROW_RE.match(stripped):
                refined.append(line)
                continue

            if _GHERKIN_HEADER_RE.match(stripped):
                refined.append(line)
                last_step_prefix = None
                if stripped.startswith(("Scenario:", "Scenario Outline:", "Background:")):
                    inside_block = True
                elif stripped.startswith(("Examples:", "Feature:")):
                    inside_block = False
                continue

            if not inside_block:
                refined.append(line)
                continue

            if not _GHERKIN_STEP_RE.match(stripped):
                prefix = "And" if last_step_prefix else "Given"
                stripped = f"{prefix} {stripped}"
                last_step_prefix = prefix
            else:
                m = _GHERKIN_STEP_RE.match(stripped)
                if m:
                    last_step_prefix = m.group(1)

            refined.append("  " + stripped)

        return "\n".join(refined)