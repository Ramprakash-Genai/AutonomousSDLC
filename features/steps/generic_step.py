import json
from behave import step, use_step_matcher

from agents.planner_agent import PlannerAgent
from agents.execution_agent import ExecutionAgent
from agents.auto_script_generator_agent import StepDefinitionGenerator
from config.logger import get_logger

use_step_matcher("re")

logger = get_logger()
planner = PlannerAgent()
executor = ExecutionAgent()
step_defs = StepDefinitionGenerator(out_dir="features/steps")


def _docstring(context):
    return getattr(context, "text", None)


def _table(context):
    return getattr(context, "table", None)


def _parse_planned(planned_json: str) -> dict:
    # PlannerAgent should return JSON string; we enforce it here.
    if isinstance(planned_json, (tuple, list)) and planned_json:
        planned_json = planned_json[0]
    if isinstance(planned_json, dict):
        return planned_json
    return json.loads(planned_json)


@step(r"(?P<raw_step>.+)")
def handle_any_step(context, raw_step):
    """
    Single handler supports ANY BDD step wording.
    Behave provides step text without Given/When/Then keyword.
    Also supports table/docstring via context.table/context.text.
    """
    logger.info(f"Step started: {raw_step}")

    planned_json = planner.plan_step(
        raw_step, table=_table(context), docstring=_docstring(context)
    )

    planned = _parse_planned(planned_json)
    action = planned.get("action")
    page = planned.get("page") or "_global"
    target = planned.get("target")

    # Try to reuse existing page helper function (no duplicate creation)
    reused = False
    if action and target:
        mod = step_defs.load_module(page)
        fn_name = step_defs.func_name(action, target)
        if mod and hasattr(mod, fn_name):
            logger.info(
                f"♻️ Reusing existing step implementation: {page}_definitions.{fn_name}"
            )
            getattr(mod, fn_name)(
                executor, context, json.dumps(planned, ensure_ascii=False)
            )
            reused = True

    # If not reused, execute normally
    if not reused:
        executor.execute(context, json.dumps(planned, ensure_ascii=False))

        # After success, generate helper implementation for future reuse
        if action and target:
            created_fn = step_defs.upsert(page, action, target)
            logger.info(
                f"✅ Stored step implementation: {page}_definitions.{created_fn}"
            )

    logger.info(f"Step completed: {raw_step}")
