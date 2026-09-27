"""The rules :class:`~sm_records.settings.RecordsSettings` enforces, as plain
functions.

Functions rather than validator bodies because some of their callers are not
pydantic. :mod:`sm_records.boot` needs the same answer about a
``public_route_prefix`` that reached it anyway — a row stored before the rule
existed — without an exception and without taking the host down at
``on_startup``; and a test wants to ask what is wrong with a value without
constructing a settings object around it. Split from ``settings.py`` for the
300-line cap, along that seam.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from sm_records import constants

__all__ = [
    "DEFAULT_PUBLIC_ROUTE_PREFIX",
    "check_content_locales",
    "check_media_api_prefix",
    "check_public_route_prefix",
]

DEFAULT_PUBLIC_ROUTE_PREFIX: Final = "/api/records/public"
"""Where the anonymous read API lives unless an operator moves it. Named
because :mod:`sm_records.boot` falls back to it for a stored value that does
not validate — see :func:`check_public_route_prefix`."""

_LOCALE_RE: Final = re.compile(constants.LOCALE_PATTERN)
"""Compiled once — :func:`check_content_locales` runs on every settings
hydration and on every settings-screen save."""


_FORBIDDEN_PREFIXES: Final = (
    constants.ROUTE_PREFIX_API,
    constants.VIEW_PREFIX,
    "/api",
    "/admin",
)
"""Paths the anonymous exemption may not cover. The rule is *ancestry*, not
equality: the exemption is a ``startswith`` over a prefix terminating in
``/``, so a value that is a parent of any of these hands every ``GET`` under
it to anonymous callers — ``AuthMiddleware`` is disabled for the whole
subtree, other modules' routes included."""


def check_public_route_prefix(value: str) -> str:
    """The rule :attr:`RecordsSettings.public_route_prefix` must satisfy.

    A function rather than only a validator body because :mod:`sm_records.boot`
    needs the same answer about a value that reached it anyway — a row stored
    before this rule existed — without a pydantic exception and without
    taking the host down at ``on_startup``.

    Three refusals, each with a failure mode behind it: a value with no
    leading ``/`` made ``PublicRouteRegistry.add_prefix`` assert and killed
    the lifespan, leaving the setting editable only through the app that
    would not start; ``/`` (or an empty value, which normalises to it)
    exempted every ``GET`` in the host; and a parent of the admin API or the
    admin views exempted those. Anything *under* the admin API's prefix is
    fine — the exemption cannot reach upwards.
    """
    if not value.startswith("/"):
        raise ValueError("must start with '/'")
    trimmed = value.rstrip("/")
    if not trimmed:
        raise ValueError("must name at least one path segment, so it cannot be '/'")
    for reserved in _FORBIDDEN_PREFIXES:
        if reserved == trimmed or reserved.startswith(f"{trimmed}/"):
            raise ValueError(
                f"{value!r} is {reserved!r} or a parent of it, so exempting it from "
                "authentication would expose the admin surface to anonymous callers"
            )
    return value


_MEDIA_PREFIX_RE: Final = re.compile(r"^(?:/[A-Za-z0-9._~!$&'()*+,;=:@%-]+)+/?$")
"""A root-relative path: one or more ``/segment`` parts of RFC 3986 path
characters, nothing else — no scheme, no host, no query, no fragment, no
whitespace or backslash."""


def check_media_api_prefix(value: str | None) -> str | None:
    """The rule :attr:`~sm_records.settings.RecordsSettings.media_api_prefix`
    must satisfy, normalised to no trailing ``/``.

    ``None`` (detect) and ``""`` (off) pass through — a whitespace-only value
    is the empty one, because that is what a cleared text box means. Anything
    else must be a path on this host: the picker calls it from the browser
    with the session cookie, so an absolute URL would either lose the cookie
    or hand it to another origin, and a scheme-relative ``//host`` is an
    absolute URL in disguise. The admin screens' CSP is the second reason:
    ``connect-src`` is ``'self'`` unless a module widens it.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith("//") or not _MEDIA_PREFIX_RE.match(stripped):
        raise ValueError(
            "must be a path on this host starting with '/', such as '/api/file-storage' "
            "— or null to detect it, or an empty string to turn the media picker off"
        )
    return stripped.rstrip("/")


def check_content_locales(locales: Sequence[str], default_locale: str) -> None:
    """The three rules :mod:`sm_records.locales` then takes for granted.

    Checked here and not at the call sites because every one of them — the
    create path, the translation endpoint, the public list — would otherwise
    have to answer "what if the configured list is empty", and the honest
    answer is that such an install cannot serve anything.

    The tag grammar is deliberately narrower than BCP 47's (lowercase, two or
    three letters, hyphen-separated subtags): a content locale is a column
    value *and* a query-string value, so accepting two spellings of one
    language would let ``?locale=de`` and ``?locale=DE`` address different
    sets. Resolution is case-insensitive
    (:func:`sm_records.locales.resolve`); the configured list is not.

    The default has to be one of them — a mismatch would 404 every public read
    at the first request instead of failing here, where an operator is looking
    at the field they just typed.
    """
    if not locales:
        raise ValueError("content_locales must list at least one locale")
    bad = [tag for tag in locales if not _LOCALE_RE.match(tag)]
    if bad:
        raise ValueError(
            f"content_locales {bad} are not language tags; each must match "
            f"{constants.LOCALE_PATTERN} (lowercase, e.g. 'en', 'pt-br')"
        )
    if default_locale not in locales:
        raise ValueError(
            f"default_content_locale {default_locale!r} is not in content_locales {list(locales)}"
        )


class StoredSourcesOnly:
    """A mixin that leaves a settings class with exactly one source.

    The hydrator passes stored overrides as keyword arguments, so any field has
    exactly two answers: what the database says, or the default the class
    declares. Dropping the env sources rather than merely not documenting them
    is deliberate — a stray ``SM_RECORDS_*`` in a shell or a deploy manifest
    would otherwise quietly outrank the value an operator can see and edit on
    the Settings screen.

    A mixin here rather than a method on ``RecordsSettings`` for that module's
    file cap. It is behaviour, not a rule about a value, which makes it the one
    thing in this module that is not a plain function.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Init kwargs only — no env, no ``.env``, no secrets directory."""
        return (init_settings,)
