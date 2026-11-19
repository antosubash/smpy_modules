"""Server-side strings for the reminder mail, from events' own catalogue.

A reminder speaks the language the follower was using when they followed, which is not
necessarily any request's: the worker has no ``I18nRegistry``, so the strings come straight from
``locales/<locale>.json`` (the ``reminders.mail`` section), a copy of records' reader. A key a
locale lacks falls back to English, and a missing key to itself, so a gap is visible, not an
error. Only shipped catalogues are ever looked up.
"""

from __future__ import annotations

import importlib.resources
import json
from functools import cache
from typing import Any, Final

from sm_events.core import constants

__all__ = ["FALLBACK", "catalogue_locale", "text"]

FALLBACK: Final = "en"
_SECTION: Final = "reminders.mail"


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            out.update(_flatten(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = str(value)
    return out


@cache
def _catalogue(locale: str) -> dict[str, str]:
    path = importlib.resources.files(constants.PACKAGE) / "locales" / f"{locale}.json"
    try:
        return _flatten(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return {}


@cache
def _available() -> frozenset[str]:
    folder = importlib.resources.files(constants.PACKAGE) / "locales"
    return frozenset(
        entry.name.removesuffix(".json")
        for entry in folder.iterdir()
        if entry.name.endswith(".json")
    )


def catalogue_locale(*candidates: str | None) -> str:
    """The first candidate with a shipped catalogue (a primary subtag counts: ``de-at`` is
    German), else English."""
    available = _available()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        lowered = candidate.strip().lower()
        for tag in (lowered, lowered.split("-")[0]):
            if tag in available:
                return tag
    return FALLBACK


def text(key: str, locale: str | None, **params: Any) -> str:
    """``reminders.mail.<key>`` in ``locale``, else English."""
    full = f"{_SECTION}.{key}"
    template = _catalogue(locale or FALLBACK).get(full) or _catalogue(FALLBACK).get(full, full)
    return template.format_map(params)
