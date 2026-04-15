from pytest_bdd import given, when, then, parsers


# Catch-all for ANY Given step
@given(parsers.re(r"(?P<raw_step>.+)"))
def given_any_step(sdlc_context, raw_step):
    sdlc_context.run_step(raw_step)


# Catch-all for ANY When step
@when(parsers.re(r"(?P<raw_step>.+)"))
def when_any_step(sdlc_context, raw_step):
    sdlc_context.run_step(raw_step)


# Catch-all for ANY Then step
@then(parsers.re(r"(?P<raw_step>.+)"))
def then_any_step(sdlc_context, raw_step):
    sdlc_context.run_step(raw_step)