"""The notification a contact-form submission sends its recipients (#101).

Plain text, from ``templates/notify.txt`` (``string.Template``) with the strings
from this module's own catalogue (``locales/<locale>.json``,
``public_submissions.mail.notify.*``) in the host's default language: it goes
to staff, not to the visitor. Every public field is listed as ``label:
value`` with the type's own labels, and the message links to the record in
the console. There is no ``Reply-To``: the framework's ``MailMessage`` cannot
carry one, and copying the visitor's address into a header would be the
first thing a mail-bombing script tries.

The visitor's values leave the database here and only here, by design.
"""

from __future__ import annotations

import importlib.resources
import json
from functools import cache
from string import Template
from typing import Any, Final
from urllib.parse import urlsplit

from simple_module_core.mail import MailMessage

from sm_records import constants
from sm_records.models import Record, RecordType
from sm_records.services._payload import field_defs

__all__ = ["notification", "text"]

_PREFIX: Final = "public_submissions.mail.notify."
_FALLBACK: Final = "en"
_EMPTY: Final = "—"


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


def text(key: str, locale: str | None, **params: Any) -> str:
    """``public_submissions.mail.notify.<key>`` in ``locale``, else English."""
    full = f"{_PREFIX}{key}"
    template = _catalogue(locale or _FALLBACK).get(full) or _catalogue(_FALLBACK).get(full, full)
    return template.format_map(params)


@cache
def _template() -> Template:
    path = importlib.resources.files(__package__) / "templates" / "notify.txt"
    return Template(path.read_text(encoding="utf-8"))


def _value(value: Any) -> str:
    if value is None or value == "" or value == []:
        return _EMPTY
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "✓" if value else "✗"
    return str(value)


def _lines(rtype: RecordType, record: Record) -> str:
    config = rtype.public_submissions or {}
    labels = {entry.key: entry.label for entry in field_defs(rtype)}
    data = record.data or {}
    return "\n".join(
        f"{labels.get(key, key)}: {_value(data.get(key))}"
        for key in config.get("public_fields", [])
    )


def notification(
    rtype: RecordType, record: Record, *, to: str, base_url: str, locale: str | None
) -> MailMessage:
    site = urlsplit(base_url).netloc or base_url
    link = f"{base_url}{constants.VIEW_PREFIX}/{rtype.key}/{record.uuid}"
    body = _template().substitute(
        intro=text("intro", locale, type=rtype.label, site=site),
        fields=_lines(rtype, record),
        open_label=text("open", locale),
        link=link,
        footer=text("footer", locale, site=site),
    )
    return MailMessage(
        to=to, subject=text("subject", locale, type=rtype.label, site=site), text=body
    )
