import os
from playwright.sync_api import sync_playwright


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def _is_closed(obj) -> bool:
    try:
        return obj is None or obj.is_closed()
    except Exception:
        return obj is None


def get_page(context, browser_name: str = None, headless: bool = None):
    """
    Execution/runtime page provider (pytest/behave style).
    Caches Playwright objects on a context-like object.

    Stores on context:
      - context._pw
      - context.browser
      - context.browser_context
      - context.page
    """
    browser_name = (browser_name or os.getenv("BROWSER", "chromium")).strip().lower()
    if headless is None:
        headless = _env_bool("HEADLESS", default=False)

    default_timeout_ms = _env_int("PLAYWRIGHT_TIMEOUT_MS", 180000)
    nav_timeout_ms = _env_int("PLAYWRIGHT_NAV_TIMEOUT_MS", 180000)

    if not hasattr(context, "_pw") or context._pw is None:
        context._pw = sync_playwright().start()

    def _launch_browser():
        pw = context._pw
        if browser_name == "firefox":
            return pw.firefox.launch(headless=headless)
        if browser_name == "webkit":
            return pw.webkit.launch(headless=headless)
        return pw.chromium.launch(headless=headless)

    if not hasattr(context, "browser") or _is_closed(getattr(context, "browser", None)):
        context.browser = _launch_browser()
        context.browser_context = context.browser.new_context()
        context.page = context.browser_context.new_page()
        context.page.set_default_timeout(default_timeout_ms)
        context.page.set_default_navigation_timeout(nav_timeout_ms)
        return context.page

    if (
        not hasattr(context, "browser_context")
        or getattr(context, "browser_context", None) is None
    ):
        try:
            context.browser_context = context.browser.new_context()
        except Exception:
            context.browser = _launch_browser()
            context.browser_context = context.browser.new_context()

    if not hasattr(context, "page") or _is_closed(getattr(context, "page", None)):
        try:
            context.page = context.browser_context.new_page()
        except Exception:
            context.browser = _launch_browser()
            context.browser_context = context.browser.new_context()
            context.page = context.browser_context.new_page()

        context.page.set_default_timeout(default_timeout_ms)
        context.page.set_default_navigation_timeout(nav_timeout_ms)

    return context.page


def close_all(context):
    """Close all Playwright resources stored on an execution context."""
    try:
        if hasattr(context, "browser_context") and context.browser_context:
            context.browser_context.close()
    except Exception:
        pass

    try:
        if hasattr(context, "browser") and context.browser:
            context.browser.close()
    except Exception:
        pass

    try:
        if hasattr(context, "_pw") and context._pw:
            context._pw.stop()
    except Exception:
        pass

    for attr in ("page", "browser_context", "browser", "_pw"):
        try:
            if hasattr(context, attr):
                setattr(context, attr, None)
        except Exception:
            pass


# ============================================================
# Preview / Discovery (FastAPI-safe) – Canonical Implementation
# ============================================================
def get_preview_page():
    """
    Preview-safe Playwright lifecycle.
    Never reuses execution get_page().

    Returns: (pw, browser, context, page)
    Caller must close: context.close(), browser.close(), pw.stop()
    """
    pw = sync_playwright().start()

    browser_name = os.getenv("PREVIEW_BROWSER", "chromium").strip().lower()
    headless = _env_bool("PREVIEW_HEADLESS", default=True)

    if browser_name == "firefox":
        browser = pw.firefox.launch(headless=headless)
    elif browser_name == "webkit":
        browser = pw.webkit.launch(headless=headless)
    else:
        browser = pw.chromium.launch(headless=headless)

    # ✅ Important for enterprise networks / cert / SSO redirects
    ignore_https = _env_bool("PREVIEW_IGNORE_HTTPS_ERRORS", default=True)

    context = browser.new_context(ignore_https_errors=ignore_https)
    page = context.new_page()

    page.set_default_timeout(_env_int("PLAYWRIGHT_TIMEOUT_MS", 180000))
    page.set_default_navigation_timeout(_env_int("PLAYWRIGHT_NAV_TIMEOUT_MS", 180000))

    return pw, browser, context, page


# Keep backward-compat alias (some old code may call this name)
def start_preview_browser():
    return get_preview_page()
