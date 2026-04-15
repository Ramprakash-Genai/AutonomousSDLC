import os
import time
import pytest
from types import SimpleNamespace
from pathlib import Path
from dotenv import load_dotenv

from tools.playwright_runner import get_page, close_all
from agents.planner_agent import PlannerAgent
from agents.execution_agent import ExecutionAgent
from agents.script_recorder import ScriptRecorder
from agents.feature_refiner_agent import FeatureRefinerAgent, RefinerConfig


# -----------------------------------------------------------------------------
# ✅ Permanent .env loading (project-root based for pytest)
# -----------------------------------------------------------------------------
def _load_env_once() -> None:
    """
    Load .env from project root reliably for pytest runs.

    conftest.py is in project root in your repo, so:
      PROJECT_ROOT = Path(__file__).resolve().parent

    If you later move conftest.py into tests/, change to parents[1].
    """
    override = os.getenv("SDLC_DOTENV_OVERRIDE", "0").strip() == "1"
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=override)


_load_env_once()


pytest_plugins = [
    "tests.steps.generic_steps",
]

STEP_TIMEOUT_SECONDS = int(os.getenv("SDLC_STEP_TIMEOUT_SECONDS", "60"))
PW_ACTION_TIMEOUT_MS = int(os.getenv("PW_ACTION_TIMEOUT_MS", "5000"))
PW_NAV_TIMEOUT_MS = int(os.getenv("PW_NAV_TIMEOUT_MS", "15000"))


def pytest_sessionstart(session):
    """
    Auto-refine .feature files once before pytest-bdd collects scenarios.
    """
    enabled = os.getenv("SDLC_AUTO_REFINE_FEATURES", "1").strip() == "1"
    if not enabled:
        print("ℹ️ SDLC_AUTO_REFINE_FEATURES=0 → skipping feature refinement")
        return

    in_place = os.getenv("SDLC_REFINE_IN_PLACE", "1").strip() == "1"
    features_dir = Path(os.getenv("SDLC_FEATURES_DIR", "features")).resolve()

    if not features_dir.exists():
        print(f"⚠️ Features dir not found: {features_dir}")
        return

    use_llm = os.getenv("SDLC_REFINE_USE_LLM", "1").strip() == "1"
    agent = FeatureRefinerAgent(RefinerConfig(use_llm=use_llm))

    skip_dirs = {"_normalized", ".pytest_cache", "steps"}
    feature_files = []
    for fp in features_dir.rglob("*.feature"):
        if any(part in skip_dirs for part in fp.parts):
            continue
        if fp.name.endswith(".bak"):
            continue
        feature_files.append(fp)

    if not feature_files:
        return

    print(f"🛠️ Auto-refining {len(feature_files)} feature file(s)")
    for feature_path in feature_files:
        raw = feature_path.read_text(encoding="utf-8")
        refined = agent.refine(raw)
        if in_place:
            feature_path.write_text(refined, encoding="utf-8")

    print("✅ Feature refinement completed.")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


@pytest.fixture(scope="session")
def planner():
    return PlannerAgent()


@pytest.fixture(scope="session")
def executor():
    return ExecutionAgent()


@pytest.fixture
def sdlc_context(request, planner, executor):
    ctx = SimpleNamespace()

    ctx.recorder = ScriptRecorder(out_dir="generated_tests", mask_secrets=True)
    ctx.recorder.start_scenario(request.node.name)

    get_page(ctx)
    if hasattr(ctx, "page") and ctx.page is not None:
        ctx.page.set_default_timeout(PW_ACTION_TIMEOUT_MS)
        ctx.page.set_default_navigation_timeout(PW_NAV_TIMEOUT_MS)

    ctx.step_timeout_seconds = STEP_TIMEOUT_SECONDS

    def run_step(raw_step: str):
        ctx.raw_step = raw_step
        start_ts = time.monotonic()
        ctx.step_deadline = start_ts + STEP_TIMEOUT_SECONDS

        planned_json = planner.plan_step(raw_step)
        executor.execute(ctx, planned_json)
        return planned_json

    ctx.run_step = run_step

    yield ctx

    try:
        failed = bool(
            hasattr(request.node, "rep_call") and request.node.rep_call.failed
        )
        path = ctx.recorder.write_pytest(force_overwrite=failed)
        print(f"✅ Generated test script: {path} (overwrite={failed})")
    except Exception as e:
        print(f"⚠️ Failed to write generated test script: {e}")

    close_all(ctx)
