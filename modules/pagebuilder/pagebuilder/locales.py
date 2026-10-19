"""The languages a page can be authored in.

Content locales are deliberately *not* the host's UI locales
(``SM_I18N_SUPPORTED_LOCALES``, which decides what language the admin chrome
speaks). The two answer different questions — a site can run an English-only
console while publishing in four languages, or the reverse — and tying them
together would make adding a translator's interface silently change what the
public site serves.

The default locale is the one that serves at the *bare* public prefix
(``/p/{slug}``). Every other locale is prefixed (``/de/p/{slug}``). That split
is what lets this feature ship without rewriting a single URL that already
exists: pages authored before there was such a thing as a locale are in the
default one, and they stay exactly where they were.

Resolved once at startup and published process-wide, mirroring
:mod:`news.settings`: the model's column default and the URL builders are pure
functions with no request to read ``app.state`` from, and threading a settings
argument through every one of them would put configuration on functions that
have nothing else to do with it.
"""

from __future__ import annotations

import logging
import re
from functools import cache

from pagebuilder.settings import PagebuilderSettings

MAX_LOCALE_LEN = 12
"""Bound on the ``locale`` column. Comfortably fits ``zh-Hant-HK``."""

LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")
"""A BCP-47 tag, lowercased. Deliberately narrower than the RFC: the tag is
part of a URL and a column value, so accepting the full grammar would let two
spellings of one language address the same page."""


_log = logging.getLogger("simple_module.pagebuilder")

_active: PagebuilderSettings | None = None
_warned = False


def use(settings: PagebuilderSettings) -> None:
    """Publish the instance the module resolved at startup."""
    global _active
    _active = settings


def reset() -> None:
    """Forget the published instance, so one test does not leak into the next."""
    global _active, _warned
    _active = None
    _warned = False


def _settings() -> PagebuilderSettings:
    """The published instance, or the pydantic defaults — never kept (#129).

    Reading before ``use()`` means the caller gets the *default*
    ``content_locales`` whatever the database says, and slugs resolve against
    the wrong language with no error. That is logged rather than raised: the
    callers that can get here (news borrowing on a host that never registered
    pagebuilder, a script, a worker that skipped the module's hooks) are
    running hosts, and turning a wrong-language risk into a crash on every
    article write is the worse failure. Logged once per unpublished stretch,
    because news borrows on every call and would otherwise log per request.
    The fallback is never stored in ``_active``, so nothing early can stand in
    for the hydrated instance.
    """
    if _active is not None:
        return _active
    global _warned
    if not _warned:
        _warned = True
        _log.warning(
            "pagebuilder.locales read before use(): falling back to the default "
            "content locales, not the configured ones"
        )
    return _defaults()


@cache
def _defaults() -> PagebuilderSettings:
    """The pure pydantic defaults, built once.

    Safe to keep, unlike the old ``_active`` fallback: it is never published,
    so ``use()`` still wins, and it holds no configuration that could go stale.
    Kept because constructing settings scans ``os.environ`` before the class
    discards that source, and news' sitemap would otherwise pay that per
    article on the event loop. Callers only read it.
    """
    return PagebuilderSettings()


def supported() -> tuple[str, ...]:
    """Every locale a page may be authored in, default first."""
    return _settings().content_locales


def default() -> str:
    """The locale that serves at the unprefixed public URL."""
    return _settings().default_content_locale


def is_default(locale: str) -> bool:
    return locale == default()


def resolve(value: str | None) -> str | None:
    """``value`` as a supported locale, or ``None``.

    Case-insensitive, because the tag arrives from a URL segment and a query
    string as often as from a select — ``/DE/p/x`` naming a real language and
    404ing would be a puzzle, not a policy.
    """
    if not value:
        return None
    lowered = value.strip().lower()
    for locale in supported():
        if locale.lower() == lowered:
            return locale
    return None


def path_prefix(locale: str) -> str:
    """The URL segment a locale contributes — ``""`` for the default one.

    Empty rather than ``/en`` on purpose: the default locale keeps the address
    it has always had, so adding a second language strands no existing link.
    """
    return "" if is_default(locale) else f"/{locale}"


def public_path(prefix: str, slug: str, locale: str) -> str:
    """Where a page in ``locale`` serves, under the module prefix ``prefix``."""
    return f"{path_prefix(locale)}{prefix.rstrip('/')}/{slug}"
