import os
from playwright.sync_api import sync_playwright


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def get_page(context, browser_name: str = None, headless: bool = None):
    """
    Returns a ready Playwright page cached on a context-like object (Behave or Pytest).
    Safe to call multiple times; recreates browser/page if they were closed.
    """
    browser_name = (browser_name or os.getenv("BROWSER", "chromium")).strip().lower()
    if headless is None:
        headless = _env_bool("HEADLESS", default=False)

    # Start Playwright once
    if not hasattr(context, "_pw") or context._pw is None:
        context._pw = sync_playwright().start()

    def _is_closed(obj) -> bool:
        try:
            return obj is None or obj.is_closed()
        except Exception:
            return obj is None

    # (Re)create browser if missing/closed
    if not hasattr(context, "browser") or _is_closed(getattr(context, "browser", None)):
        pw = context._pw
        if browser_name == "firefox":
            context.browser = pw.firefox.launch(headless=headless)
        elif browser_name == "webkit":
            context.browser = pw.webkit.launch(headless=headless)
        else:
            context.browser = pw.chromium.launch(headless=headless)

        context.browser_context = context.browser.new_context()
        context.page = context.browser_context.new_page()
        context.page.set_default_timeout(60000)
        context.page.set_default_navigation_timeout(60000)
        return context.page

    # Ensure browser_context exists
    if not hasattr(context, "browser_context") or getattr(context, "browser_context", None) is None:
        context.browser_context = context.browser.new_context()

    # Ensure page exists and is open
    if not hasattr(context, "page") or _is_closed(getattr(context, "page", None)):
        context.page = context.browser_context.new_page()
        context.page.set_default_timeout(60000)
        context.page.set_default_navigation_timeout(60000)

    return context.page


def close_all(context):
    """
    Close all playwright resources stored on context (works for Behave or Pytest).
    """
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

    # Clean references
    for attr in ("page", "browser_context", "browser", "_pw"):
        try:
            if hasattr(context, attr):
                setattr(context, attr, None)
        except Exception:
            pass
