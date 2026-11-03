"""Merge fields: ``{{first_name}}``, ``{{first_name|fallback}}`` and ``{{unsubscribe_url}}``."""

from __future__ import annotations

import html
import re

from sm_newsletter.content.urls import UNSUBSCRIBE_TAG

MAX_FALLBACK = 100
_ANY = re.compile(
    r"\{\{first_name(?:\|([^|{}]{0," + str(MAX_FALLBACK) + r"}))?\}\}|\{\{unsubscribe_url\}\}"
)


def check_merge(text: str) -> None:
    """Raise ValueError unless every ``{{`` / ``}}`` belongs to an allowed tag."""
    rest = _ANY.sub("", text)
    if "{{" in rest or "}}" in rest:
        raise ValueError("unknown or malformed merge field")


def _personalise(s: str, name: str, fallback_of, unsubscribe_url: str) -> str:
    def repl(m: re.Match[str]) -> str:
        if m.group(0) == UNSUBSCRIBE_TAG:
            return unsubscribe_url
        return name or fallback_of(m.group(1) or "")

    return _ANY.sub(repl, s)


def personalise_html(s: str, *, first_name: str | None, unsubscribe_url: str) -> str:
    """``first_name`` and the URL are escaped; a fallback is already escaped by the renderer."""
    name = html.escape((first_name or "").strip(), quote=True)
    return _personalise(s, name, lambda fb: fb, html.escape(unsubscribe_url, quote=True))


def personalise_text(s: str, *, first_name: str | None, unsubscribe_url: str) -> str:
    return _personalise(s, (first_name or "").strip(), lambda fb: fb, unsubscribe_url)
