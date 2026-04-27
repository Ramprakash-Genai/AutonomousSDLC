# backend/api/main.py
from __future__ import annotations

import os
import re
import ast
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents.config import BlueVerseClient, BlueVerseAuthError
from agents.planner_agent import plan_step
from agents.execution_agent import ExecutionAgent
from agents.memory_store import MemoryStore


# ============================================================
#  .env loading (robust)
# ============================================================
def _load_env() -> None:
    """
    Load .env from:
      1) ENV_PATH if provided
      2) nearest .env by walking up from this file
      3) current working directory
    """
    env_path = os.getenv("ENV_PATH", "").strip()
    if env_path and Path(env_path).exists():
        load_dotenv(dotenv_path=env_path, override=True)
        return

    here = Path(__file__).resolve()
    for parent in [
        here.parent,
        here.parent.parent,
        here.parent.parent.parent,
        Path.cwd(),
    ]:
        candidate = parent / ".env"
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=True)
            return

    load_dotenv(override=True)


_load_env()

app = FastAPI(title="Autonomous SDLC Jira Backend - Phase 2 (Governed)")

# ----------------------------
# CORS
# ----------------------------
FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://localhost:3001",
).split(",")
FRONTEND_ORIGINS = [o.strip() for o in FRONTEND_ORIGINS if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Jira Config
# ----------------------------
ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "").strip()
ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
ATLASSIAN_BASE_URL = os.getenv("ATLASSIAN_BASE_URL", "").strip()
JIRA_TIMEOUT = int(os.getenv("JIRA_TIMEOUT", "30"))

HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


# ----------------------------
# Helpers
# ----------------------------
def _require_jira_env():
    missing = []
    if not ATLASSIAN_EMAIL:
        missing.append("ATLASSIAN_EMAIL")
    if not ATLASSIAN_API_TOKEN:
        missing.append("ATLASSIAN_API_TOKEN")
    if not ATLASSIAN_BASE_URL:
        missing.append("ATLASSIAN_BASE_URL")
    if missing:
        raise HTTPException(
            status_code=500, detail=f"Missing Jira env vars: {', '.join(missing)}"
        )


def _base_url() -> str:
    b = ATLASSIAN_BASE_URL.strip()
    if not b:
        return ""
    if b.startswith(("http://", "https://")):
        return b.rstrip("/")
    return ("https://" + b).rstrip("/")


def _jira_url(path: str) -> str:
    return f"{_base_url()}{path}"


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)


def _get(url: str, params: Optional[dict] = None) -> requests.Response:
    return requests.get(
        url, headers=HEADERS, auth=_auth(), params=params, timeout=JIRA_TIMEOUT
    )


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [
        here.parent,
        here.parent.parent,
        here.parent.parent.parent,
        Path.cwd(),
    ]:
        if (
            (parent / "features").exists()
            or (parent / ".git").exists()
            or (parent / "pyproject.toml").exists()
        ):
            return parent
    return Path.cwd()


def _safe_story_key(story_key: str) -> str:
    s = (story_key or "").strip()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s) if s else "UNKNOWN"


def _extract_adf_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return "".join(_extract_adf_text(c) for c in node.get("content", []) or [])
    if isinstance(node, list):
        return "".join(_extract_adf_text(x) for x in node)
    return ""


def parse_description(desc: Optional[dict]) -> str:
    if not desc:
        return ""
    return _extract_adf_text(desc).strip()


def _sanitize_rendered_html(html: str) -> str:
    """
    Minimal safety cleanup for Jira rendered HTML.
    Jira renderedFields.description contains REAL HTML (not escaped).
    """
    if not html:
        return ""

    # Remove <script>...</script> blocks (real HTML)
    html = re.sub(
        r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    return html


def _extract_scenario_name(feature_text: str) -> Optional[str]:
    for line in feature_text.splitlines():
        if line.strip().lower().startswith("scenario:"):
            return line.split(":", 1)[1].strip()
    return None


def _find_duplicate_scenario(scenario_name: str) -> Optional[Path]:
    root = _repo_root()
    features_dir = root / "features"
    if not features_dir.exists():
        return None
    for f in features_dir.glob("*.feature"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if line.strip().lower().startswith("scenario:"):
                existing = line.split(":", 1)[1].strip()
                if existing == scenario_name:
                    return f
    return None


def _extract_steps_from_feature(feature_text: str) -> List[str]:
    steps = []
    for line in feature_text.splitlines():
        l = line.strip()
        if l.lower().startswith(("given ", "when ", "then ", "and ", "but ")):
            steps.append(l)
    return steps


def _safe_file_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s or "UNKNOWN"


def _test_script_path(sprint_name: str, story_key: str, scenario_name: str) -> Path:
    root = _repo_root()
    steps_dir = root / "features" / "steps" / _safe_file_name(sprint_name)
    steps_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{_safe_file_name(story_key)}_{_safe_file_name(scenario_name)}.py"
    return steps_dir / file_name


# ----------------------------
# Request models
# ----------------------------
class SearchRequest(BaseModel):
    project: str
    sprint: Optional[str] = None
    key: Optional[str] = None


class BlueVerseRefineRequest(BaseModel):
    story_key: str
    summary: str
    description: str
    project: Optional[str] = ""
    sprint: Optional[str] = ""
    existing_feature: Optional[str] = ""


class SaveFeatureRequest(BaseModel):
    story_key: str
    feature_text: str
    decision: Optional[str] = "save"  # save | overwrite | use_existing


class LocatorPreviewRequest(BaseModel):
    feature_text: str


class LocatorSaveRequest(BaseModel):
    locator_details: List[Dict[str, Any]]
    decision: Optional[str] = "save"  # save | overwrite | use_existing | cancel


class TestScriptGenerateRequest(BaseModel):
    story_key: str
    sprint_name: str
    scenario_name: str
    locator_details: List[Dict[str, Any]]


class TestScriptSaveRequest(BaseModel):
    story_key: str
    sprint_name: str
    scenario_name: str
    test_script: str
    decision: Optional[str] = "save"  # save | overwrite | reuse_existing | cancel


# ----------------------------
# Health
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ----------------------------
# Phase-1 toggle (UI uses this)
# ----------------------------
@app.post("/config/auto_refine")
def set_auto_refine(payload: dict = Body(...)):
    enabled = bool(payload.get("enabled", False))
    os.environ["SDLC_AUTO_REFINE_FEATURES"] = "1" if enabled else "0"
    return {
        "enabled": enabled,
        "SDLC_AUTO_REFINE_FEATURES": os.environ["SDLC_AUTO_REFINE_FEATURES"],
    }


# ----------------------------
# Jira endpoints (Spaces/Iterations/Stories)
# ----------------------------
@app.get("/projects")
def get_projects():
    _require_jira_env()
    url = _jira_url("/rest/api/3/project/search")
    resp = _get(url, params={"maxResults": 1000})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch projects: {resp.text}"
        )
    projects = resp.json().get("values", [])
    return {"projects": [{"key": p["key"], "name": p["name"]} for p in projects]}


def _pick_board_for_project(project_key: str) -> Optional[int]:
    boards_url = _jira_url("/rest/agile/1.0/board")
    resp = _get(boards_url, params={"projectKeyOrId": project_key, "maxResults": 50})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch boards: {resp.text}"
        )

    boards = resp.json().get("values", [])
    if not boards:
        return None
    return int(boards[0].get("id"))


@app.get("/sprints/{project_key}")
def get_sprints(project_key: str):
    _require_jira_env()
    board_id = _pick_board_for_project(project_key)
    if not board_id:
        return {"sprints": []}

    url = _jira_url(f"/rest/agile/1.0/board/{board_id}/sprint")
    resp = _get(url, params={"maxResults": 200})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch sprints: {resp.text}"
        )

    sprints = resp.json().get("values", [])
    return {
        "sprints": [
            {"id": s.get("id"), "name": s.get("name"), "state": s.get("state")}
            for s in sprints
        ]
    }


@app.get("/stories/{sprint_id}")
def get_stories(sprint_id: int):
    _require_jira_env()
    url = _jira_url(f"/rest/agile/1.0/sprint/{sprint_id}/issue")
    resp = _get(url, params={"maxResults": 500})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch issues for sprint: {resp.text}"
        )

    issues = resp.json().get("issues", [])
    out = []
    for i in issues:
        fields = i.get("fields", {}) or {}
        itype = (fields.get("issuetype") or {}).get("name", "")
        # Keep only Story type (as your UI expects stories)
        if itype and itype.lower() == "story":
            out.append({"key": i.get("key"), "summary": fields.get("summary", "")})
    return {"stories": out}


@app.post("/search")
def search_issue(req: SearchRequest):
    _require_jira_env()
    if not req.key:
        raise HTTPException(status_code=400, detail="Missing issue key")

    issue_key = req.key.strip()
    url = _jira_url(f"/rest/api/3/issue/{issue_key}")

    # ✅ KEY CHANGE: expand=renderedFields to get HTML that matches Jira UI
    params = {
        "expand": "renderedFields",
        # Keep payload light; Jira will still provide renderedFields.description
        "fields": "summary,assignee,description",
    }

    resp = _get(url, params=params)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch issue {issue_key}: {resp.text}"
        )

    issue = resp.json()
    fields = issue.get("fields", {}) or {}
    rendered = issue.get("renderedFields", {}) or {}

    summary = fields.get("summary") or ""
    assignee_obj = fields.get("assignee") or {}
    assignee = assignee_obj.get("displayName") or assignee_obj.get("name") or "-"

    # Plain text (used by Refiner Agent payload later)
    description_plain = parse_description(fields.get("description"))

    # HTML (used by UI preview to match Jira)
    description_html = _sanitize_rendered_html(rendered.get("description") or "")

    return {
        "key": issue.get("key", issue_key),
        "summary": summary,
        "assignee": assignee,
        "description": description_plain,  # keep existing contract for agents
        "description_html": description_html,  # NEW: exact Jira-like rendered view
    }


# ----------------------------
# BlueVerse Refiner (THIS FIXES YOUR 'Refiner Agent failed: Not Found')
# ----------------------------
@app.post("/blueverse/refine_feature")
def blueverse_refine_feature(req: BlueVerseRefineRequest):
    """
    Uses agents.config.BlueVerseClient which relies on:
      BLUEVERSE_URL
      BLUEVERSE_TOKEN
      BLUEVERSE_REFINER_SPACE
      BLUEVERSE_REFINER_FLOWID
    (as per your .env)
    """
    load_dotenv(override=True)
    try:
        client = BlueVerseClient()

        raw_feature = (
            req.existing_feature.strip()
            if req.existing_feature and req.existing_feature.strip()
            else f"Feature: {req.summary}\n\n  Scenario: {req.summary}\n"
            f"    When {req.description}"
        )

        refined = client.refine_feature(raw_feature=raw_feature, constraints=None)
        clean_text = (refined or "").strip()
        if not clean_text:
            raise HTTPException(
                status_code=500, detail="Refiner returned empty feature text."
            )

        # Some environments return dict-like string; keep the literal_eval safety
        if clean_text.startswith("{") and "refined_feature" in clean_text:
            try:
                parsed = ast.literal_eval(clean_text)
                if isinstance(parsed, dict) and isinstance(
                    parsed.get("refined_feature"), str
                ):
                    clean_text = parsed["refined_feature"].strip()
            except Exception:
                pass

        return {"feature": clean_text}

    except BlueVerseAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# Save Feature with Duplicate Scenario Check (used by your UI)
# ----------------------------
@app.post("/feature/save")
def save_feature(req: SaveFeatureRequest):
    story_key = _safe_story_key(req.story_key)
    feature_text = (req.feature_text or "").strip()

    if not feature_text:
        raise HTTPException(status_code=400, detail="feature_text is empty")

    scenario_name = _extract_scenario_name(feature_text)
    if not scenario_name:
        raise HTTPException(status_code=400, detail="Scenario name not found")

    duplicate_file = _find_duplicate_scenario(scenario_name)

    if duplicate_file and req.decision == "save":
        return {
            "status": "DUPLICATE_SCENARIO",
            "scenario": scenario_name,
            "existing_file": str(duplicate_file),
        }

    root = _repo_root()
    features_dir = root / "features"
    features_dir.mkdir(parents=True, exist_ok=True)

    out_path = features_dir / f"{story_key}.feature"

    if duplicate_file and req.decision == "overwrite":
        duplicate_file.write_text(feature_text, encoding="utf-8")
        return {"status": "OVERWRITTEN", "path": str(duplicate_file)}

    if duplicate_file and req.decision == "use_existing":
        return {"status": "USING_EXISTING", "path": str(duplicate_file)}

    out_path.write_text(feature_text, encoding="utf-8")
    return {"status": "SAVED", "path": str(out_path)}


# ----------------------------
# BDD → Planner JSON (used by later pipeline)
# ----------------------------
@app.post("/feature/plan")
def feature_plan(payload: Dict[str, Any] = Body(...)):
    feature_text = (payload.get("feature_text") or "").strip()
    if not feature_text:
        raise HTTPException(status_code=400, detail="feature_text missing")

    steps = _extract_steps_from_feature(feature_text)
    plans = []
    for step in steps:
        plans.append(
            plan_step({"step": step, "table": None, "docstring": None}).get("plan")
        )
    return {"plans": plans}


# ----------------------------
# Locator Preview (Option‑B Discovery) – FIXED (NO CONTEXT)
# ----------------------------
@app.post("/feature/locator/preview")
def locator_preview(req: LocatorPreviewRequest):
    try:
        agent = ExecutionAgent()
        return agent.preview_generate_locator_details(feature_text=req.feature_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Locator preview error: {str(e)}")


# ----------------------------
# Save Locator Details (Governed)
# ----------------------------
@app.post("/feature/locator/save")
def locator_save(req: LocatorSaveRequest):
    """
    Save locator details with duplicate validation.
    Decision values:
      - save         => check duplicates; if found return DUPLICATE_LOCATORS
      - use_existing => do nothing (reuse existing locators)
      - overwrite    => overwrite matching entries
      - cancel       => stop flow
    """
    store = MemoryStore()

    # ✅ Cancel should immediately stop and let UI reset the conversation
    if (req.decision or "").lower() == "cancel":
        return {"status": "CANCELLED"}

    duplicates: List[Dict[str, Any]] = []

    # Step 1: Detect duplicates FIRST (based only on locator_details)
    for loc in req.locator_details:
        matches = store.find_exact_duplicates(
            page=loc["page"],
            host=loc["host"],
            action=loc["action"],
            target=loc["target"],
            locator=loc["locator"],
            locator_type=loc.get("locator_type"),
        )
        if matches:
            duplicates.append(loc)

    # Step 2: If duplicates found and decision=save, return duplicates for UI decision
    if duplicates and (req.decision or "save") == "save":
        return {
            "status": "DUPLICATE_LOCATORS",
            "locator_details": duplicates,
        }

    # Step 3: If user chose reuse existing, do not write anything
    if (req.decision or "").lower() == "use_existing":
        return {"status": "LOCATORS_REUSED"}

    # Step 4: Apply overwrite (no append option anymore)
    overwrite = (req.decision or "").lower() == "overwrite"
    for loc in req.locator_details:
        store.upsert(
            page=loc["page"],
            host=loc["host"],
            action=loc["action"],
            target=loc["target"],
            locator=loc["locator"],
            overwrite=overwrite,
            append_new=False,  # ✅ removed
            locator_type=loc.get("locator_type"),
        )

    return {"status": "LOCATORS_SAVED"}


@app.post("/feature/testscript/generate")
def generate_test_script(req: TestScriptGenerateRequest):
    """
    Generates a pytest-playwright test script string for review.
    Uses BlueVerse TestScriptGeneratorAgent (NOT local code).
    Does NOT save to disk.
    """
    load_dotenv(override=True)
    try:
        client = BlueVerseClient()

        # NOTE: This method will be added in agents/config.py next
        result = client.generate_test_script(
            story_key=req.story_key,
            sprint_name=req.sprint_name,
            scenario_name=req.scenario_name,
            locator_details=req.locator_details,
        )

        # BlueVerse may return dict-like or plain string; normalize safely
        script = None
        if isinstance(result, dict):
            script = (
                result.get("test_script")
                or result.get("output")
                or result.get("result")
            )
        elif isinstance(result, str):
            script = result

        script = (script or "").strip()

        # ✅ SAFETY: unwrap dict-like string if returned as text
        if script.startswith("{") and "test_script" in script:
            try:
                parsed = ast.literal_eval(script)
                if isinstance(parsed, dict) and isinstance(
                    parsed.get("test_script"), str
                ):
                    script = parsed["test_script"].strip()
            except Exception:
                pass

        if not script:
            raise HTTPException(
                status_code=500, detail="BlueVerse returned empty test_script"
            )

        return {
            "status": "SCRIPT_GENERATED",
            "scenario_name": req.scenario_name,
            "test_script": script,
        }

    except BlueVerseAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Test script generation failed: {str(e)}"
        )


@app.post("/feature/testscript/save")
def save_test_script(req: TestScriptSaveRequest):
    """
    Saves approved pytest-playwright script under:
      root/features/steps/<sprintname>/<story>_<scenario>.py

    Duplicate check:
      - if file exists and decision=save => return DUPLICATE_TEST_SCRIPT with existing content
      - reuse_existing => do nothing, return REUSED
      - overwrite => replace file
      - cancel => stop flow
    """
    if (req.decision or "").lower() == "cancel":
        return {"status": "CANCELLED"}

    path = _test_script_path(req.sprint_name, req.story_key, req.scenario_name)

    # duplicate check
    if path.exists() and (req.decision or "save") == "save":
        existing = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "status": "DUPLICATE_TEST_SCRIPT",
            "path": str(path),
            "existing_test_script": existing,
        }

    # reuse existing
    if path.exists() and (req.decision or "").lower() == "reuse_existing":
        return {"status": "TEST_SCRIPT_REUSED", "path": str(path)}

    # overwrite or first save
    path.write_text(req.test_script or "", encoding="utf-8")
    return {"status": "TEST_SCRIPT_SAVED", "path": str(path)}
