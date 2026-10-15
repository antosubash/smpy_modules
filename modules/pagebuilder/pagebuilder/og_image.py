"""The image a link preview shows for a page.

The SEO panel promises that a blank Social image "falls back to the first image
on the page"; this is that fallback. "First" is document order: the page's
content, each block's nested slots before its later siblings, then any legacy
``zones``. Only the Image block counts — a hero's background or a logo strip is
decoration, and choosing one of those would preview the wrong thing.
"""

from __future__ import annotations

from typing import Any

# Visited first and in this order, whatever order the stored JSON keeps its
# keys in: Postgres JSONB sorts them shortest-first, which would put legacy
# zones ahead of the page's own content.
_ORDER = ("content", "props", "zones")


def first_image(data: Any) -> str | None:
    """The ``src`` of the first Image block in a Puck document, if any."""
    if isinstance(data, dict):
        if data.get("type") == "Image":
            src = (data.get("props") or {}).get("src")
            if isinstance(src, str) and src.strip():
                return src.strip()
        children = [data.get(key) for key in _ORDER]
        if "type" not in data:
            # A zones map or a block's props: any value may hold blocks (slots
            # live under arbitrary prop names, and inside array items).
            children += [value for key, value in data.items() if key not in _ORDER]
    elif isinstance(data, list):
        children = data
    else:
        return None
    for child in children:
        found = first_image(child)
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
    return src
