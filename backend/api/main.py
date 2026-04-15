from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

import os
import json
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from pathlib import Path
import subprocess
import signal
from typing import Optional

# ----------------------------
# Load .env safely (repo root)
# ----------------------------
# This loads .env from the current working directory by default
# If you prefer explicit path, set ENV_PATH in your environment.
env_path = os.getenv("ENV_PATH")
if env_path:
    load_dotenv(dotenv_path=env_path, override=True)
else:
    # Try repo root ".env" (walk upwards)
    # If file is inside backend/api, go up until .env is found
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
            break

app = FastAPI(title="Autonomous SDLC Jira Backend")

# ----------------------------
# Config (NO hardcoding)
# ----------------------------
ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "").strip()
ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
ATLASSIAN_BASE_URL = os.getenv(
    "ATLASSIAN_BASE_URL", ""
).strip()  # e.g. https://xxx.atlassian.net

# Frontend origins (comma-separated) -> allows Vite 5173 + CRA 3000/3001 etc.
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

# Requests config
TIMEOUT = int(os.getenv("JIRA_TIMEOUT", "30"))
headers = {"Accept": "application/json", "Content-Type": "application/json"}


def _require_jira_env():
    if not ATLASSIAN_EMAIL or not ATLASSIAN_API_TOKEN or not ATLASSIAN_BASE_URL:
        raise HTTPException(
            status_code=500,
            detail="Missing Jira environment variables. Please set ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN, ATLASSIAN_BASE_URL in .env",
        )


def _base_url() -> str:
    """
    Ensure base URL always looks like:
      https://<domain>.atlassian.net
    and has no trailing slash.
    """
    b = ATLASSIAN_BASE_URL.strip()
    if not b:
        return b
    if b.startswith("http://") or b.startswith("https://"):
        return b.rstrip("/")
    return ("https://" + b).rstrip("/")


def _auth():
    return HTTPBasicAuth(ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)


def _get(url: str, params: Optional[dict] = None):
    r = requests.get(url, headers=headers, auth=_auth(), params=params, timeout=TIMEOUT)
    return r


def _post(url: str, payload: dict):
    r = requests.post(url, headers=headers, auth=_auth(), json=payload, timeout=TIMEOUT)
    return r


# ----------------------------
# Codegen process state (single session for hackathon)
# ----------------------------
app.state.codegen_proc = None

APPROVED_DIR = Path("app") / "Approved_feature_files"


def safe_folder_name(name: str) -> str:
    return (
        str(name)
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("|", "_")
        .strip()
    )


# ----------------------------
# Request Models
# ----------------------------
class SearchRequest(BaseModel):
    project: str
    sprint: Optional[str] = None
    key: Optional[str] = None


class TestCaseRequest(BaseModel):
    User_Story_Summary: str
    User_Story_Description: str
    story_details: dict
    prompt_file: str


class ApproveRequest(BaseModel):
    sprint_name: str
    story_number: str
    generated_test_case: str
    file_ext: Optional[str] = "spec"


class AutomationRequest(BaseModel):
    story_number: str
    sprint_name: str
    feature_content: str
    locator_mapping: str
    prompt_file: str


class CodegenStartRequest(BaseModel):
    browser: str  # chrome | edge | firefox
    url: str


# ----------------------------
# Helpers
# ----------------------------
def parse_description(desc):
    """
    Parse Jira rich-text description and normalize whitespace for UI readability.
    - trims leading/trailing spaces from each extracted text line
    - keeps bullet structure
    """
    if not desc or "content" not in desc:
        return ""

    text_parts = []

    def add_text(t: str):
        t = (t or "").strip()
        if t:
            text_parts.append(t)

    for block in desc.get("content", []):
        if block.get("type") == "paragraph":
            for item in block.get("content", []):
                if item.get("type") == "text":
                    add_text(item.get("text", ""))

        elif block.get("type") == "bulletList":
            for li in block.get("content", []):
                for para in li.get("content", []):
                    for item in para.get("content", []):
                        if item.get("type") == "text":
                            add_text("• " + item.get("text", ""))

    # Join with newlines and remove accidental blank rows
    return "\n".join([line for line in text_parts if line.strip()])


def _jira_url(path: str) -> str:
    return f"{_base_url()}{path}"


def _pick_board_for_project(project_key: str) -> Optional[int]:
    """
    Jira Agile uses Boards -> Sprints. We must pick a board.
    Strategy (universal, not hardcoded):
      - Query boards by projectKeyOrId
      - Prefer Scrum/Kanban boards that have a location matching the project
      - Fallback to the first board if any
    """
    boards_url = _jira_url("/rest/agile/1.0/board")
    resp = _get(boards_url, params={"projectKeyOrId": project_key})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch boards: {resp.text}"
        )

    boards = resp.json().get("values", [])
    if not boards:
        return None

    # Prefer board where location.projectKey matches
    for b in boards:
        loc = b.get("location") or {}
        if (loc.get("projectKey") or "").upper() == project_key.upper():
            return b.get("id")

    return boards[0].get("id")


# ----------------------------
# Health
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "FastAPI Jira backend is running."}


# ============================================================
#  Jira (Spaces/Iterations/Stories)  - Real data (no hardcode)
# ============================================================


# Spaces = Projects
@app.get("/projects")
def get_projects():
    _require_jira_env()
    url = _jira_url("/rest/api/3/project/search")

    # Jira projects are paginated sometimes. We'll fetch first 1000 for hackathon.
    resp = _get(url, params={"maxResults": 1000})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch projects: {resp.text}"
        )

    projects = resp.json().get("values", [])
    return {"projects": [{"key": p["key"], "name": p["name"]} for p in projects]}


# Alias for UI naming
@app.get("/jira/spaces")
def jira_spaces():
    return get_projects()


# Iterations = Sprints
@app.get("/sprints/{project_key}")
def get_sprints(project_key: str):
    _require_jira_env()

    board_id = _pick_board_for_project(project_key)
    if not board_id:
        return {"sprints": []}

    url = _jira_url(f"/rest/agile/1.0/board/{board_id}/sprint")
    resp = _get(url, params={"maxResults": 100})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch sprints: {resp.text}"
        )

    sprints = resp.json().get("values", [])
    return {
        "sprints": [
            {"id": s["id"], "name": s["name"], "state": s.get("state")} for s in sprints
        ]
    }


# Alias query-based iterations
@app.get("/jira/iterations")
def jira_iterations(space: str):
    return get_sprints(space)


# Stories = Issues in Sprint (filter to Story optionally)
@app.get("/stories/{sprint_id}")
def get_stories(sprint_id: int):
    _require_jira_env()

    url = _jira_url(f"/rest/agile/1.0/sprint/{sprint_id}/issue")
    # Keep it simple: return issues in sprint. If you want only Story issue type,
    # we can add JQL filtering later using /search.
    resp = _get(url, params={"maxResults": 200})
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch stories: {resp.text}"
        )

    issues = resp.json().get("issues", [])
    stories = []
    for i in issues:
        fields = i.get("fields", {})
        issuetype = (fields.get("issuetype") or {}).get("name", "")
        # include only Stories by default (universal)
        if issuetype.lower() == "story":
            stories.append({"key": i["key"], "summary": fields.get("summary", "")})

    return {"stories": stories}


# Alias query-based stories
@app.get("/jira/stories")
def jira_stories(iteration: str):
    return get_stories(int(iteration))


# Story Details
@app.post("/search")
def search_issue(req: SearchRequest):
    _require_jira_env()

    jql_parts = [f"project = {req.project}"]
    if req.sprint:
        jql_parts.append(f"sprint = {req.sprint}")
    if req.key:
        jql_parts.append(f"key = {req.key}")
    jql = " AND ".join(jql_parts)

    url = _jira_url("/rest/api/3/search/jql")
    payload = {
        "jql": jql,
        "fields": ["summary", "description", "status", "assignee", "issuetype"],
    }

    resp = _post(url, payload)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400, detail=f"Failed to fetch issues: {resp.text}"
        )

    issues = resp.json().get("issues", [])
    if not issues:
        raise HTTPException(status_code=404, detail=f"No issue found for JQL: {jql}")

    issue = issues[0]
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")
    return {
        "key": issue["key"],
        "summary": fields.get("summary", ""),
        "description": parse_description(fields.get("description")),
        "assignee": assignee.get("displayName") if assignee else "Unassigned",
    }


# ============================================================
#  Existing feature generation / approvals / automation
#  (kept intact — only minor safety improvements)
# ============================================================

# NOTE: Keep your Models import where it actually exists in your repo.
# If your project path differs, adjust import accordingly.


@app.post("/generate_testcase")
def generate_testcase(req: TestCaseRequest):
    try:
        if not os.path.exists(req.prompt_file):
            raise HTTPException(status_code=400, detail="Prompt file not found")

        with open(req.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        model = Models()
        generated = model.generate_test_case(req.model_dump(), prompt_text)
        return {"generated_test_case": generated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/approve_testcase")
def approve_testcase(req: ApproveRequest):
    try:
        sprint_folder = safe_folder_name(req.sprint_name)
        ext = (req.file_ext or "spec").lstrip(".")

        folder = APPROVED_DIR / sprint_folder
        folder.mkdir(parents=True, exist_ok=True)

        file_name = f"{req.story_number}.{ext}"
        file_path = folder / file_name

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(req.generated_test_case)

        return {
            "file_name": file_name,
            "file_path": str(file_path),
            "sprint_name": sprint_folder,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_automation_script")
def generate_automation_script(req: AutomationRequest):
    try:
        if not os.path.exists(req.prompt_file):
            raise HTTPException(
                status_code=400, detail="Automation prompt file not found"
            )

        with open(req.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        model = Models()
        script = model.generate_automation_script(
            story_number=req.story_number,
            sprint_name=req.sprint_name,
            feature_content=req.feature_content,
            locator_mapping=req.locator_mapping,
            prompt_text=prompt_text,
        )

        return {"automation_script": script}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Codegen endpoints (kept, with minor safety)
# ============================================================


@app.get("/codegen/status")
def codegen_status():
    proc = app.state.codegen_proc
    running = proc is not None and proc.poll() is None
    return {"running": running}


@app.post("/codegen/stop")
def codegen_stop():
    proc = app.state.codegen_proc
    if proc is None or proc.poll() is not None:
        app.state.codegen_proc = None
        return {"stopped": True, "message": "No active codegen process."}

    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.kill(proc.pid, signal.SIGTERM)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop codegen: {e}")

    app.state.codegen_proc = None
    return {"stopped": True}


@app.post("/codegen/start")
def codegen_start(req: CodegenStartRequest):
    proc = app.state.codegen_proc
    if proc is not None and proc.poll() is None:
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.kill(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        app.state.codegen_proc = None

    browser = (req.browser or "chrome").lower().strip()
    url = (req.url or "").strip()

    if not url:
        raise HTTPException(
            status_code=400,
            detail="URL is empty. Please provide a valid application URL.",
        )
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(
            status_code=400, detail='URL must start with "http://" or "https://".'
        )

    if browser not in ["chrome", "edge", "firefox"]:
        raise HTTPException(
            status_code=400, detail="Browser must be one of: chrome, edge, firefox"
        )

    runner_path = Path("app") / "codegen" / "codegen_runner.mjs"
    if not runner_path.exists():
        raise HTTPException(
            status_code=400, detail=f"Codegen runner not found: {runner_path}"
        )

    cmd = ["node", str(runner_path), "--browser", browser, "--url", url]

    try:
        app.state.codegen_proc = subprocess.Popen(
            cmd,
            cwd=str(Path(".")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        return {"started": True, "message": f"Codegen started in {browser} for {url}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start codegen: {e}")
