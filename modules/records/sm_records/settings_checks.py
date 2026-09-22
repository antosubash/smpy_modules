"""The rules :class:`~sm_records.settings.RecordsSettings` enforces, as plain
functions.

Functions rather than validator bodies because two of the three callers are not
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
from typing import Any, Final

from sm_records import constants

__all__ = [
    "DEFAULT_PUBLIC_ROUTE_PREFIX",
    "check_content_locales",
    "check_limits",
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

_LOCALE_RE: Final = re.compile(constants.LOCALE_PATTERN)
"""Compiled once — :meth:`RecordsSettings._check_locales` runs on every
settings hydration and on every settings-screen save."""


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


def check_limits(settings: Any) -> None:
    """The two cross-field ceilings ``RecordsSettings`` has to hold together.

    A default page size above the maximum would be clamped away on every
    request by :meth:`~sm_records.settings.RecordsSettings.clamp_page_size`,
    which is a setting that silently does not mean what it says; an indexed
    field ceiling above the field ceiling is a limit that can never bind.
    Both are refused where the operator can see the field they just typed.
    Takes the settings object rather than four integers: it is called from a
    model validator that has one, and the names below are then the names the
    error messages use.
    """
    if settings.default_page_size > settings.max_page_size:
        raise ValueError(
            f"default_page_size ({settings.default_page_size}) must not exceed "
            f"max_page_size ({settings.max_page_size})"
        )
    if settings.max_indexed_fields_per_type > settings.max_fields_per_type:
        raise ValueError(
            f"max_indexed_fields_per_type ({settings.max_indexed_fields_per_type}) "
            f"must not exceed max_fields_per_type ({settings.max_fields_per_type})"
        )


def clamp_page_size(settings: Any, requested: int | None) -> int:
    """The page size a list endpoint actually uses.

    One owner for the rule, because four call sites must agree on it: the
    admin list, the referrers panel, the anonymous read API and the record-list
    view. ``None`` means "the caller did not ask" and gets
    ``default_page_size``; anything above ``max_page_size`` is clamped rather
    than refused, so an anonymous caller probing the ceiling learns nothing and
    gets a usable page either way.

    A function here rather than the body of ``RecordsSettings.clamp_page_size``
    only for that module's file cap; the method remains the call site.
    """
    return max(min(requested or settings.default_page_size, settings.max_page_size), 1)
