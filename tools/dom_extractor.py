def get_dom(page):
    """
    Returns a combined DOM snapshot (main document + iframe DOMs).

    Design rules (IMPORTANT):
    - NEVER raise an exception
    - NEVER mutate page state
    - Always return a STRING (may be empty)

    This function is used by:
    - LocatorAgent
    - HealingAgent
    - Locator Preview (read-only discovery mode)
    """

    # If page is invalid or None, safely return empty DOM
    if page is None:
        return ""

    parts = []

    # ---- Main document ----
    try:
        parts.append("<!-- MAIN DOCUMENT -->\n")
        html = page.content()
        if html:
            parts.append(html)
    except Exception:
        # Page may be closed or not ready; ignore safely
        pass

    # ---- Iframes (best-effort) ----
    try:
        frames = getattr(page, "frames", None) or []
        main_frame = getattr(page, "main_frame", None)

        for i, frame in enumerate(frames):
            try:
                # Skip main frame (already captured)
                if main_frame is not None and frame == main_frame:
                    continue

                parts.append(
                    f"\n<!-- IFRAME {i}: url={getattr(frame, 'url', '')} -->\n"
                )

                frame_html = frame.content()
                if frame_html:
                    parts.append(frame_html)

            except Exception:
                # Individual frame failure must NOT break DOM collection
                continue

    except Exception:
        # Something unexpected; still return what we have
        pass

    # Always return a single joined string
    try:
        return "\n".join(parts)
    except Exception:
        return ""
