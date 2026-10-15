"""The image a link preview shows for a page.

The SEO panel promises that a blank Social image "falls back to the first image
on the page"; this is that fallback. "First" is document order: the page's
content, each block's nested slots before its later siblings, then any legacy
``zones``. Only the Image block counts — a hero's background or a logo strip is
decoration, and choosing one of those would preview the wrong thing.
"""

from __future__ import annotations

from typing import Any


def first_image(data: Any) -> str | None:
    """The ``src`` of the first Image block in a Puck document, if any."""
    if isinstance(data, dict):
        if data.get("type") == "Image":
            src = (data.get("props") or {}).get("src")
            if isinstance(src, str) and src.strip():
                return src.strip()
        for key in ("content", "props", "zones"):
            found = first_image(data.get(key))
            if found:
                return found
        if "type" not in data:
            # A zones map or a block's props: every value may hold blocks.
            for key, value in data.items():
                if key in ("content", "props", "zones"):
                    continue
                found = first_image(value)
                if found:
                    return found
    elif isinstance(data, list):
        for item in data:
            found = first_image(item)
            if found:
                return found
    return None


def og_image(explicit: str | None, data: Any, base_url: str) -> str | None:
    """The page's own Social image, else its first image, as an absolute URL.

    Link-preview crawlers resolve nothing: ``og:image`` has to be absolute, and
    an uploaded image is stored as a root-relative ``/media/...`` path.
    """
    src = (explicit or "").strip() or first_image(data)
    if src and src.startswith("/") and not src.startswith("//"):
        return f"{base_url}{src}"
    return src or None
