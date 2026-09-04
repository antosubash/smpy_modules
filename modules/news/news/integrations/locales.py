"""The languages an article can be written in.

They are pagebuilder's, not news'. An article *is* a page, so a language this
module offered that pagebuilder did not would be one no article could actually
be written in — and two lists to keep in step.

A sibling of :mod:`news.integrations.pagebuilder` rather than part of it,
because that file is at the repo's 300-line cap and because these are the only
functions here that answer a question about configuration rather than about
data. Same rule applies: nothing outside ``news.integrations`` imports
``pagebuilder``.
"""

from __future__ import annotations

from pagebuilder import locales as _pagebuilder_locales


def content_locales() -> tuple[str, ...]:
    """Every language a page — and so an article — may be authored in."""
    return _pagebuilder_locales.supported()


def default_locale() -> str:
    """The language that serves at the unprefixed public URL."""
    return _pagebuilder_locales.default()


def is_default_locale(locale: str) -> bool:
    return _pagebuilder_locales.is_default(locale)


def resolve_locale(value: str | None) -> str | None:
    """``value`` as a configured content locale, or ``None`` if it is not one."""
    return _pagebuilder_locales.resolve(value)


def locale_path_prefix(locale: str) -> str:
    """The URL segment a language contributes — ``""`` for the default one."""
    return _pagebuilder_locales.path_prefix(locale)
