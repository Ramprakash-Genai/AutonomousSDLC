# agents/config.py
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, List

import requests
from dotenv import load_dotenv

_ENV_LOADED = False


def _find_env_file() -> Optional[Path]:
    here = Path(__file__).resolve()
    for parent in [
        here.parent,
        here.parent.parent,
        here.parent.parent.parent,
        Path.cwd(),
    ]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def _load_env_once(force: bool = False) -> None:
    global _ENV_LOADED
    if _ENV_LOADED and not force:
        return

    env_file = _find_env_file()
    if env_file:
        load_dotenv(dotenv_path=str(env_file), override=True)
    else:
        load_dotenv(override=True)

    _ENV_LOADED = True


class BlueVerseAuthError(Exception):
    """Raised when BlueVerse authentication fails (401)."""


@dataclass
class BlueVerseConfig:
    url: str
    token: str

    # IMPORTANT: BlueVerse expects these names in payload
    space_name: str = ""
    flow_id: str = ""

    @classmethod
    def from_env(cls) -> "BlueVerseConfig":
        # Always reload for long-running FastAPI
        _load_env_once(force=True)

        url = os.getenv("BLUEVERSE_URL", "").strip()
        token = os.getenv("BLUEVERSE_TOKEN", "").strip()

        token_file = os.getenv("BLUEVERSE_TOKEN_FILE", "").strip()
        if token_file:
            p = Path(token_file).expanduser()
            if p.exists():
                file_token = p.read_text(encoding="utf-8").strip()
                if file_token:
                    token = file_token

        # ---- Routing resolution (most important fix) ----
        # Prefer Refiner-specific vars if present (your .env uses these)
        ref_space = os.getenv("BLUEVERSE_REFINER_SPACE", "").strip()
        ref_flow = os.getenv("BLUEVERSE_REFINER_FLOWID", "").strip()

        # Fallback: generic names some code uses
        generic_space = os.getenv(
            "BLUEVERSE_SPACE_NAME",
            os.getenv("BLUEVERSE_SPACE_ID", os.getenv("SPACE_ID", "")),
        ).strip()
        generic_flow = os.getenv(
            "BLUEVERSE_FLOW_ID", os.getenv("FLOW_ID", os.getenv("FLOWID", ""))
        ).strip()

        space_name = ref_space or generic_space
        flow_id = ref_flow or generic_flow

        if not url:
            raise RuntimeError("Missing BLUEVERSE_URL in .env")
        if not token:
            raise RuntimeError(
                "Missing BLUEVERSE_TOKEN (or BLUEVERSE_TOKEN_FILE) in .env"
            )

        return cls(url=url, token=token, space_name=space_name, flow_id=flow_id)


def _jwt_expired(token: str, skew_seconds: int = 30) -> bool:
    """Best-effort JWT exp check (no signature verification)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return False
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        )
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            return False
        return time.time() > (float(exp) - skew_seconds)
    except Exception:
        return False


class BlueVerseClient:
    """
    BlueVerse chat client.

    Your BLUEVERSE_URL already includes the endpoint:
        https://.../chatservice/chat

    BlueVerse requires payload fields:
        query, space_name, flow_id
    """

    def __init__(self, cfg: Optional[BlueVerseConfig] = None, timeout: int = 300):
        self.timeout = timeout
        self.session = requests.Session()
        self._cfg = cfg

    def _cfg_now(self) -> BlueVerseConfig:
        # Always read fresh routing + token for FastAPI calls
        return BlueVerseConfig.from_env()

    def _headers(self) -> Dict[str, str]:
        cfg = self._cfg_now()
        if _jwt_expired(cfg.token):
            raise BlueVerseAuthError('{"exp":"token expired"}')
        return {
            "Authorization": f"Bearer {cfg.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def chat(
        self, query: str, extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        cfg = self._cfg_now()
        url = cfg.url.rstrip("/")

        # ✅ REQUIRED payload keys for your BlueVerse endpoint
        payload: Dict[str, Any] = {
            "query": query,
            "space_name": cfg.space_name,
            "flow_id": cfg.flow_id,
        }

        # Some deployments accept alternate keys too; harmless to include as compatibility
        payload["space_id"] = cfg.space_name  # fallback mapping
        payload["flowId"] = cfg.flow_id  # camelCase fallback

        if extra:
            payload.update(extra)

        resp = self.session.post(
            url, headers=self._headers(), json=payload, timeout=self.timeout
        )

        if resp.status_code == 401:
            raise BlueVerseAuthError(resp.text)

        if resp.status_code == 400:
            raise RuntimeError(f"BlueVerse HTTP 400: {resp.text}")

        if resp.status_code == 404:
            raise RuntimeError(f"BlueVerse HTTP 404: {resp.text}")

        if not resp.ok:
            raise RuntimeError(f"BlueVerse HTTP {resp.status_code}: {resp.text}")

        return resp.json()

    def chat_with_routing(
        self,
        query: str,
        space_name: str,
        flow_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call BlueVerse chat endpoint but override routing (space_name + flowId).
        This is needed when you have multiple agents (Refiner, TestScriptGenerator, etc.)
        using the SAME BlueVerse base URL + token.
        """
        cfg = self._cfg_now()
        url = cfg.url.rstrip("/")

        # Required payload keys (include both snake_case + camelCase for compatibility)
        payload: Dict[str, Any] = {
            "query": query,
            "space_name": (space_name or "").strip(),
            "flow_id": (flow_id or "").strip(),
            "flowId": (flow_id or "").strip(),
            "space_id": (space_name or "").strip(),  # compatibility fallback
        }

        if extra:
            payload.update(extra)

        resp = self.session.post(
            url, headers=self._headers(), json=payload, timeout=self.timeout
        )

        if resp.status_code == 401:
            raise BlueVerseAuthError(resp.text)

        if resp.status_code == 400:
            raise RuntimeError(f"BlueVerse HTTP 400: {resp.text}")

        if resp.status_code == 404:
            raise RuntimeError(f"BlueVerse HTTP 404: {resp.text}")

        if not resp.ok:
            raise RuntimeError(f"BlueVerse HTTP {resp.status_code}: {resp.text}")

        return resp.json()

    def generate_test_script(
        self,
        story_key: str,
        sprint_name: str,
        scenario_name: str,
        locator_details: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate pytest-playwright test script using BlueVerse TestScriptGeneratorAgent.

        Uses env vars:
          - BLUEVERSE_TEST_SCRIPT_GENERATOR_SPACE
          - BLUEVERSE_TEST_SCRIPT_GENERATOR_FLOWID
        """
        _load_env_once(force=True)

        space = os.getenv("BLUEVERSE_TEST_SCRIPT_GENERATOR_SPACE", "").strip()
        flow = os.getenv("BLUEVERSE_TEST_SCRIPT_GENERATOR_FLOWID", "").strip()

        if not space or not flow:
            raise RuntimeError(
                "Missing BLUEVERSE_TEST_SCRIPT_GENERATOR_SPACE or BLUEVERSE_TEST_SCRIPT_GENERATOR_FLOWID in .env"
            )

        # Build a strict query for the agent (agent already has system prompt, but we keep input structured)
        query = (
            "Generate a pytest-playwright test script for one scenario using ONLY the locator JSON.\n"
            "Return output as JSON with key: test_script.\n\n"
            f"Story key: {story_key}\n"
            f"Sprint name: {sprint_name}\n"
            f"Scenario name: {scenario_name}\n\n"
            "Locator JSON:\n"
            f"{json.dumps(locator_details or [], indent=2)}"
        )

        data = self.chat_with_routing(query=query, space_name=space, flow_id=flow)

        # Normalize output shapes:
        # Some agents return {"test_script": "..."} directly,
        # some wrap under "response"/"text"/"data"
        if isinstance(data, dict):
            if isinstance(data.get("test_script"), str):
                return {"test_script": data["test_script"]}

            if isinstance(data.get("response"), str):
                # sometimes response is JSON-like string; try to parse
                try:
                    parsed = json.loads(data["response"])
                    if isinstance(parsed, dict) and isinstance(
                        parsed.get("test_script"), str
                    ):
                        return {"test_script": parsed["test_script"]}
                except Exception:
                    # if it's raw python code, wrap it
                    return {"test_script": data["response"]}

            if isinstance(data.get("text"), str):
                return {"test_script": data["text"]}

            inner = data.get("data")
            if isinstance(inner, dict):
                for k in ("test_script", "response", "text"):
                    v = inner.get(k)
                    if isinstance(v, str):
                        # try JSON parse for response field
                        if k == "response":
                            try:
                                parsed = json.loads(v)
                                if isinstance(parsed, dict) and isinstance(
                                    parsed.get("test_script"), str
                                ):
                                    return {"test_script": parsed["test_script"]}
                            except Exception:
                                return {"test_script": v}
                        return {"test_script": v}

        # Fallback: if BlueVerse returned a string directly
        if isinstance(data, str) and data.strip():
            return {"test_script": data.strip()}

        raise RuntimeError("TestScriptGeneratorAgent returned no valid test_script")

    def refine_feature(
        self, raw_feature: str, constraints: Optional[Dict[str, Any]] = None
    ) -> str:
        prompt = (
            f"Return ONLY valid Gherkin (.feature file) as plain text.\n\n{raw_feature}"
        )

        data = self.chat(prompt, extra=constraints or {})

        # ✅ HARD GUARANTEE: return ONLY the feature string
        if isinstance(data, dict):
            if isinstance(data.get("refined_feature"), str):
                return data["refined_feature"]

            if isinstance(data.get("response"), str):
                return data["response"]

            if isinstance(data.get("text"), str):
                return data["text"]

            inner = data.get("data")
            if isinstance(inner, dict):
                for k in ("refined_feature", "response", "text"):
                    v = inner.get(k)
                    if isinstance(v, str):
                        return v

            # ❌ NEVER stringify the dict for UI
            raise RuntimeError("Refiner returned no valid Gherkin text")

        if isinstance(data, str):
            return data

        raise RuntimeError("Invalid refiner response type")
