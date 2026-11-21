"""The content languages the public surface serves, settled once at startup.

The default language keeps the bare public prefix (``/events/...``) and every other is
prefixed with its tag (``/de/events/...``), as news and pagebuilder address theirs.
Resolved process-wide, as news does: the URL builders are pure functions with no request
to read ``app.state`` from. Before startup a single English locale answers.
"""

from __future__ import annotations

__all__ = ["default", "is_default", "path_prefix", "reset", "supported", "use"]

_FALLBACK = ("en",)
_active: tuple[str, ...] = _FALLBACK


def use(*locales: str) -> None:
    """Publish the content locales, default first. An empty list keeps English."""
    global _active
    _active = tuple(dict.fromkeys(locales)) or _FALLBACK


def reset() -> None:
    """Forget the published locales, so one test does not leak into the next."""
    use(*_FALLBACK)


def supported() -> tuple[str, ...]:
    return _active


def default() -> str:
    return _active[0]


def is_default(locale: str) -> bool:
    return locale == default()


def path_prefix(locale: str) -> str:
    """``""`` for the default language, ``"/de"`` for another."""
    return "" if is_default(locale) else f"/{locale}"
