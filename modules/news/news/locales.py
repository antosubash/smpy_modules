"""The languages an article can be written in.

News did not need this while an article *was* a pagebuilder page: the language
was the page's, and :mod:`news.integrations.locales` read it straight off that
module. An article owns its content now, so it owns its language too — and the
column's default, the URL builders and the public routes all have to answer
"what languages?" on a host that does not run pagebuilder at all.

So the vocabulary lives here, and pagebuilder is *borrowed from* rather than
depended on. Where both modules are installed the two lists are deliberately
the same one: an article is still a document on the same site as the pages, and
offering a language pagebuilder did not would mean two lists to keep in step.
Where pagebuilder is absent the fallback is a single default locale, which is
exactly the monolingual behaviour every existing site already has.

The import of the seam is deferred and guarded for the same reason every import
in :mod:`news.integrations.pagebuilder` is: this module is reached from
:mod:`news.models`, and a hard import there would make the whole package —
including its migrations — unloadable without the neighbour.

Resolved process-wide rather than per request, mirroring :mod:`news.settings`:
the model's column default and the URL builders are pure functions with no
request to read ``app.state`` from.
"""

from __future__ import annotations

from collections.abc import Sequence

from news.constants import FALLBACK_LOCALE

_active: tuple[tuple[str, ...], str] | None = None


def use(supported_locales: Sequence[str], default_locale: str) -> None:
    """Publish the vocabulary the module resolved at startup."""
    global _active
    _active = (tuple(supported_locales), default_locale)


def reset() -> None:
    """Forget the published vocabulary, so one test does not leak into the next."""
    global _active
    _active = None


def _vocabulary() -> tuple[tuple[str, ...], str]:
    """What was published, what pagebuilder says, or a monolingual default.

    Not cached: ``use`` is the fast path once a host has booted, and the borrow
    below is a ``sys.modules`` hit plus pagebuilder's own cached settings. A
    cache here would instead make a test that reconfigures pagebuilder's
    locales silently read the previous run's answer.
    """
    if _active is not None:
        return _active
    return _borrowed() or ((FALLBACK_LOCALE,), FALLBACK_LOCALE)


def _borrowed() -> tuple[tuple[str, ...], str] | None:
    """Pagebuilder's content locales, or ``None`` where it is not installed.

    The calls are inside the ``try`` as well as the import: the seam defers its
    own ``pagebuilder`` import into each function, so importing it succeeds on a
    host without the module and only *asking* it anything raises.
    """
    try:
        from news.integrations.locales import content_locales, default_locale

        return tuple(content_locales()), default_locale()
    except ImportError:
        return None


def supported() -> tuple[str, ...]:
    """Every language an article may be authored in, default first."""
    return _vocabulary()[0]


def default() -> str:
    """The language that serves at the unprefixed public URL."""
    return _vocabulary()[1]


def is_default(locale: str) -> bool:
    return locale == default()


def resolve(value: str | None) -> str | None:
    """``value`` as a supported locale, or ``None``.

    Case-insensitive, because the tag arrives from a URL segment and a query
    string as often as from a select — ``/DE/news/x`` naming a real language
    and 404ing would be a puzzle, not a policy.
    """
    if not value:
        return None
    lowered = value.strip().lower()
    for locale in supported():
        if locale.lower() == lowered:
            return locale
    return None


def path_prefix(locale: str) -> str:
    """The URL segment a language contributes — ``""`` for the default one.

    Empty rather than ``/en`` on purpose: the default locale keeps the address
    it has always had, so adding a second language strands no existing link.
    """
    return "" if is_default(locale) else f"/{locale}"
