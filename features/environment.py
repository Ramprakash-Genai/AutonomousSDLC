from agents.script_recorder import ScriptRecorder


def before_scenario(context, scenario):
    context.recorder = ScriptRecorder(out_dir="generated_tests", mask_secrets=True)
    context.recorder.start_scenario(scenario.name)


def after_scenario(context, scenario):
    try:
        if hasattr(context, "recorder") and context.recorder:
            path = context.recorder.write_pytest()
            print(f"✅ Generated test script: {path}")
    except Exception as e:
        print(f"⚠️ Failed to write generated test script: {e}")


def after_all(context):
    try:
        if hasattr(context, "browser_context"):
            context.browser_context.close()
    except Exception:
        pass
    try:
        if hasattr(context, "browser"):
            context.browser.close()
    except Exception:
        pass
    try:
        if hasattr(context, "_pw"):
            context._pw.stop()
    except Exception:
        pass