"""Text from a file, made safe for the module's fields (Ruling 25).

A file's text is not typed by a person, so what the single-line rule would refuse is **stripped**
(control and direction characters, line separators, invisible spaces) rather than refusing the
event. A description is plain text: HTML-escaped, turned into paragraphs, and then passed
through the same allow-list sanitiser every description goes through; a URL is appended only if
it is http or https. Nothing here ever returns markup that came from the file.
"""

from __future__ import annotations

import html
import re
from typing import Final
from urllib.parse import urlsplit

from sm_events.content.richtext import clean
from sm_events.core import constants
from sm_events.web.schemas._fields import strip_unsafe

__all__ = ["clean_title", "description_html", "http_url", "unescape", "venue"]

_ESCAPE: Final = re.compile(r"\\(.)", re.DOTALL)
_SPACES: Final = re.compile(r"\s+")
_BLANK: Final = re.compile(r"\n[ \t]*\n+")


def unescape(text: str) -> str:
    """RFC 5545 TEXT escapes (a backslash before ``n``, a comma, a semicolon or a backslash);
    any other escaped character stays as it is."""
    return _ESCAPE.sub(lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def clean_title(raw: str) -> tuple[str, tuple[str, ...]]:
    """One clean line of at most 300 characters, or the placeholder (noted ``untitled``)."""
    title = _SPACES.sub(" ", strip_unsafe(raw.replace("\n", " "))).strip()[: constants.TITLE_MAX]
    if title:
        return title, ()
    return constants.IMPORT_UNTITLED, ("untitled",)


def venue(raw: str) -> str | None:
    text = _SPACES.sub(" ", strip_unsafe(raw.replace("\n", " "))).strip()
    return text[: constants.VENUE_MAX] or None


def http_url(raw: str | None) -> str | None:
    """``raw`` if it is a plain http(s) URL of sane length, else ``None``."""
    if not raw:
        return None
    text = raw.strip()
    if len(text) > constants.URL_MAX or text != strip_unsafe(text) or " " in text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    return text if parts.scheme in ("http", "https") and parts.netloc else None


def description_html(plain: str, url: str | None) -> tuple[str, tuple[str, ...]]:
    """The description as sanitised HTML, and the notes (``description_truncated``)."""
    notes: tuple[str, ...] = ()
    text = strip_unsafe(plain, newlines=True).replace("\r", "")
    if len(text) > constants.IMPORT_DESCRIPTION_MAX:
        text, notes = text[: constants.IMPORT_DESCRIPTION_MAX], ("description_truncated",)
    paragraphs = [p.strip("\n") for p in _BLANK.split(text.strip()) if p.strip()]
    body = "".join(
        "<p>" + "<br>".join(html.escape(line.strip()) for line in p.split("\n")) + "</p>"
        for p in paragraphs
    )
    if (link := http_url(url)) is not None:
        shown = html.escape(link)
        body += f'<p><a href="{shown}">{shown}</a></p>'
    return clean(body), notes
