"""Copy the server renders itself, outside any request's language (R12, S9).

The email footer and the unsubscribe page speak the host's
``i18n_default_locale``: an email has no reader's request, and the page must
match the email it was opened from. The text comes from the app's i18n registry
(``newsletter.<section>.<key>``), else from the package's own ``en.json``, so a
host whose registry has not loaded newsletter's catalogue still renders.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from sm_newsletter.core import constants

__all__ = ["host_locale", "server_copy"]

_DEFAULT_LOCALE = "en"


def host_locale(app: Any) -> str:
    settings = getattr(getattr(app.state, "sm", None), "settings", None)
    return getattr(settings, "i18n_default_locale", "") or _DEFAULT_LOCALE


@cache
def _package_messages() -> dict[str, Any]:
    raw = (resources.files("sm_newsletter") / "locales" / "en.json").read_text(encoding="utf-8")
    return json.loads(raw)


def server_copy(app: Any, section: str, keys: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """``(locale, {key: text})`` for ``newsletter.<section>.<key>`` in the host's language."""
    locale = host_locale(app)
    registry = getattr(getattr(app.state, "sm", None), "i18n_registry", None)
    messages = registry.messages(locale) if registry is not None else {}
    fallback = _package_messages()[section]
    prefix = f"{constants.LOCALE_NAMESPACE}.{section}."
    return locale, {key: messages.get(prefix + key) or fallback[key] for key in keys}
