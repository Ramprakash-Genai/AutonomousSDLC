import os
import json
import requests
from dataclasses import dataclass
from typing import List
import re
import ast
from pathlib import Path
from dotenv import load_dotenv


# -----------------------------------------------------------------------------
# ✅ Permanent .env loading (project-root based)
# -----------------------------------------------------------------------------
def _load_env_once() -> None:
    """
    Load .env from project root reliably (not dependent on current working directory).

    PROJECT ROOT is assumed to be the folder that contains:
      - conftest.py
      - agents/ (this file is in agents/)
      - .env

    override behavior:
      - SDLC_DOTENV_OVERRIDE=1 will force .env to override existing OS env values
      - otherwise existing OS env values remain higher priority (recommended)
    """
    override = os.getenv("SDLC_DOTENV_OVERRIDE", "0").strip() == "1"

    # agents/config.py -> parents[1] = project root
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=override)


_load_env_once()


@dataclass
class BlueVerseConfig:
    url: str
    token: str
    refiner_space: str
    refiner_flow_id: str
    planner_space: str
    planner_flow_id: str
    locator_space: str
    locator_flow_id: str
    healing_space: str
    healing_flow_id: str

    @staticmethod
    def from_env() -> "BlueVerseConfig":
        url = (
            os.getenv("BLUEVERSE_URL")
            or "https://blueverse-foundry.ltimindtree.com/chatservice/chat"
        ).strip()

        token = (os.getenv("BLUEVERSE_TOKEN") or "").strip()
        if not token:
            raise RuntimeError(
                "BLUEVERSE_TOKEN is missing. Please set it in .env or environment variables."
            )

        refiner_space = (os.getenv("BLUEVERSE_REFINER_SPACE") or "").strip()
        refiner_flow_id = (os.getenv("BLUEVERSE_REFINER_FLOWID") or "").strip()

        planner_space = (os.getenv("BLUEVERSE_PLANNER_SPACE") or "").strip()
        planner_flow_id = (os.getenv("BLUEVERSE_PLANNER_FLOWID") or "").strip()

        locator_space = (os.getenv("BLUEVERSE_LOCATOR_SPACE") or "").strip()
        locator_flow_id = (os.getenv("BLUEVERSE_LOCATOR_FLOWID") or "").strip()

        healing_space = (os.getenv("BLUEVERSE_HEALING_SPACE") or "").strip()
        healing_flow_id = (os.getenv("BLUEVERSE_HEALING_FLOWID") or "").strip()

        # All 4 agents are mandatory for "Groq removed permanently"
        if not refiner_space or not refiner_flow_id:
            raise RuntimeError(
                "BLUEVERSE_REFINER_SPACE or BLUEVERSE_REFINER_FLOWID is missing."
            )
        if not planner_space or not planner_flow_id:
            raise RuntimeError(
                "BLUEVERSE_PLANNER_SPACE or BLUEVERSE_PLANNER_FLOWID is missing."
            )
        if not locator_space or not locator_flow_id:
            raise RuntimeError(
                "BLUEVERSE_LOCATOR_SPACE or BLUEVERSE_LOCATOR_FLOWID is missing."
            )
        if not healing_space or not healing_flow_id:
            raise RuntimeError(
                "BLUEVERSE_HEALING_SPACE or BLUEVERSE_HEALING_FLOWID is missing."
            )

        return BlueVerseConfig(
            url=url,
            token=token,
            refiner_space=refiner_space,
            refiner_flow_id=refiner_flow_id,
            planner_space=planner_space,
            planner_flow_id=planner_flow_id,
            locator_space=locator_space,
            locator_flow_id=locator_flow_id,
            healing_space=healing_space,
            healing_flow_id=healing_flow_id,
        )


class BlueVerseClient:
    """
    Minimal BlueVerse client for calling AI Agents via /chatservice/chat.
    """

    def __init__(self, cfg: BlueVerseConfig):
        self.cfg = cfg

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg.token}",
        }

    def chat(
        self, space_name: str, flow_id: str, query: str, timeout_seconds: int = 60
    ) -> dict:
        body = {"query": query, "space_name": space_name, "flowId": flow_id}
        resp = requests.post(
            self.cfg.url, headers=self._headers(), json=body, timeout=timeout_seconds
        )
        resp.raise_for_status()
        data = resp.json()

        # Case 1: structured output nested under response dict
        if isinstance(data, dict) and isinstance(data.get("response"), dict):
            return data["response"]

        # Case 2: output inside "response" as STRING
        if isinstance(data, dict) and isinstance(data.get("response"), str):
            txt = data["response"].strip()

            try:
                parsed = json.loads(txt)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

            try:
                parsed = ast.literal_eval(txt)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

            m = re.search(r"\{.*\}", txt, flags=re.S)
            if m:
                candidate = m.group(0)
                try:
                    parsed = ast.literal_eval(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass

            raise RuntimeError(
                f"BlueVerse returned non-parseable response string: {txt[:300]}"
            )

        return data

    # Feature Refiner
    def refine_feature(self, raw_feature_text: str) -> str:
        data = self.chat(
            self.cfg.refiner_space, self.cfg.refiner_flow_id, raw_feature_text
        )
        refined = data.get("refined_feature")
        if not isinstance(refined, str) or not refined.strip():
            raise RuntimeError(
                f"BlueVerse refiner returned unexpected response: {data}"
            )
        return refined.strip()

    # Planner
    def plan_step(self, raw_input_json: dict) -> dict:
        query = json.dumps(raw_input_json, ensure_ascii=False)
        data = self.chat(self.cfg.planner_space, self.cfg.planner_flow_id, query)
        plan = data.get("plan")
        if not isinstance(plan, dict):
            raise RuntimeError(
                f"BlueVerse planner returned unexpected response: {data}"
            )
        return plan

    # Locator (expects LocatorResponse)
    def locator_candidates(self, payload: dict) -> List[str]:
        query = json.dumps(payload, ensure_ascii=False)
        data = self.chat(self.cfg.locator_space, self.cfg.locator_flow_id, query)

        if isinstance(data.get("LocatorResponse"), dict):
            inner = data["LocatorResponse"]
            cands = inner.get("candidates")
        else:
            cands = data.get("candidates")

        if not isinstance(cands, list):
            raise RuntimeError(
                f"BlueVerse locator returned unexpected response: {data}"
            )

        return [str(c).strip() for c in cands if isinstance(c, str) and c.strip()]

    # Healing (expects HealingResponse)
    def healing_candidates(self, payload: dict) -> List[str]:
        query = json.dumps(payload, ensure_ascii=False)
        data = self.chat(self.cfg.healing_space, self.cfg.healing_flow_id, query)

        if isinstance(data.get("HealingResponse"), dict):
            inner = data["HealingResponse"]
            cands = inner.get("candidates")
        else:
            cands = data.get("candidates")

        if not isinstance(cands, list):
            raise RuntimeError(
                f"BlueVerse healing returned unexpected response: {data}"
            )

        return [str(c).strip() for c in cands if isinstance(c, str) and c.strip()]
