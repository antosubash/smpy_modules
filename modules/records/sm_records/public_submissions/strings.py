"""Server-side strings from this module's own catalogue (#101).

The mail and the newsletter's landing page speak a visitor's or a recipient's
language, which is not necessarily the console's: a German subscriber's
confirmation is German whatever the operator's cookie says. Neither the outbox
worker nor the after-commit task has the host's ``I18nRegistry``, so the
strings come straight from ``locales/<locale>.json`` — host overrides do not
apply here. A key a locale lacks falls back to English, and a missing key to
itself, so a gap is visible rather than an error.
"""

from __future__ import annotations

import importlib.resources
import json
from functools import cache
from typing import Any, Final

from sm_records import constants

__all__ = ["FALLBACK", "catalogue_locale", "text"]

FALLBACK: Final = "en"


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
    """The first candidate this module has a catalogue for — its primary
    subtag counts (``de-at`` is German) — else English. Only shipped
    catalogues are ever looked up, whatever a link or a page says."""
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
    """``public_submissions.<key>`` in ``locale``, else English."""
    full = f"public_submissions.{key}"
    template = _catalogue(locale or FALLBACK).get(full) or _catalogue(FALLBACK).get(full, full)
    return template.format_map(params)
