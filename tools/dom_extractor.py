def get_dom(page):
    """
    Returns combined DOM: main page + iframe DOM.
    This helps LocatorAgent/HealingAgent when elements live in frames.
    """
    parts = []
    try:
        parts.append("<!-- MAIN DOCUMENT -->\n")
        parts.append(page.content() or "")
    except Exception:
        pass

    try:
        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            try:
                parts.append(f"\n<!-- IFRAME {i}: url={frame.url} -->\n")
                parts.append(frame.content() or "")
            except Exception:
                continue
    except Exception:
        pass

    return "\n".join(parts)