"""Everything the public surface needs wired once the settings are known.

None of this can run during app construction. Where the viewer mounts and which
languages it mounts for come from the database, and the host hydrates module
settings at *lifespan* start — so a prefix read while the app is being built is
the pydantic default no matter what an operator configured, and a router mounted
there is mounted at the wrong address. :meth:`news.module.NewsModule.on_startup`
is the first moment the answers are real, and this is what it calls.

Split out of ``module.py`` for the repo's 300-line cap, and named to match
:mod:`pagebuilder.boot`, which does the same job for the same reason.
"""

from __future__ import annotations

from fastapi import FastAPI

from news import locales


def dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one "/"."""
    return f"{prefix.rstrip('/')}/"


def publish_locales(app: FastAPI) -> None:
    """Settle which languages this site publishes in, once, at startup.

    Read from pagebuilder's *hydrated* settings rather than through its
    process-global: module startup hooks run in registration order, and news no
    longer depends on pagebuilder, so news may well go first — at which point
    that global still holds the pre-hydration defaults and the viewer would
    mount for one language on a site that configured three. The hydrate step,
    by contrast, has finished before any ``on_startup`` runs.

    Left alone where there is nothing to borrow: :mod:`news.locales` then falls
    back to a single default locale, which is the monolingual behaviour every
    site without pagebuilder has.
    """
    from news.integrations.locales import hydrated_locales

    borrowed = hydrated_locales(app)
    if borrowed is not None:
        locales.use(*borrowed)


def mount_public_routers(app: FastAPI, prefix: str) -> None:
    """The viewer, the archive and the feeds — one mount per language.

    The default language keeps the bare prefix so no article URL that already
    exists changes; every other one carries its tag, exactly as pagebuilder
    addresses pages.
    """
    from news.endpoints.public import default_locale_alias_router, public_router

    languages = locales.supported()
    for locale in languages:
        app.include_router(
            public_router(locale), prefix=f"{locales.path_prefix(locale)}{prefix}"
        )
    if len(languages) > 1:
        # ``/en/news/x`` → ``/news/x``. The default language serves unprefixed,
        # but anything that builds URLs by pasting a locale in front will ask
        # for the redundant form, and a 301 is the only useful answer.
        app.include_router(
            default_locale_alias_router(prefix),
            prefix=f"/{locales.default()}{prefix}",
        )


def exempt_public_routes(
    app: FastAPI, prefix: str, languages: tuple[str, ...]
) -> None:
    """Exempt the public article viewer from auth, one prefix per language.

    Without this every article 302s an anonymous reader to the login screen,
    which is the whole point of a public address.

    Not in ``register_public_routes`` with the API's prefixes, because those are
    constants and these are not: they depend on ``public_route_prefix`` and on
    the site's content languages, neither of which is hydrated yet at that point
    in boot. ``AuthMiddleware`` reads the registry live, so adding to it here
    works just as well.
    """
    registry = getattr(app.state, "public_routes", None)
    if registry is None:
        # No auth middleware in this app, so nothing to be exempt from.
        return
    for locale in languages:
        localised = f"{locales.path_prefix(locale)}{prefix}"
        # The trailing slash is load-bearing — these are ``startswith``
        # prefixes, so a bare "/news" would also exempt anything that merely
        # starts with those characters.
        registry.add_prefix(dir_prefix(localised), methods={"GET", "HEAD"})
        # And the bare prefix, exactly. A reader who trims the URL back to
        # "/news" is asking for the archive's front page; without this they got
        # the sign-in screen instead, because the prefix rule above only covers
        # "/news/" and the redirect to it never happens — auth runs before
        # routing. Exact rather than a second prefix on purpose: "/news" as a
        # prefix would also exempt "/newsletter-admin".
        registry.add_exact(localised.rstrip("/"), methods={"GET", "HEAD"})
    if len(languages) > 1:
        # The default language's redundant prefix, which 301s to the bare
        # address. Exempt too, or the redirect that exists to be forgiving
        # answers with a login page. The bare form has no route behind it and
        # so 404s — which is the right answer, and the reason it is listed:
        # without it the same trimmed URL answers with a sign-in page instead,
        # which reads as "this exists and you may not see it".
        alias = f"/{locales.default()}{prefix}"
        registry.add_prefix(dir_prefix(alias), methods={"GET", "HEAD"})
        registry.add_exact(alias.rstrip("/"), methods={"GET", "HEAD"})
