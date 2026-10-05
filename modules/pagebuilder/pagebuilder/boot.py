"""Everything the public surface needs wired once the settings are known.

Split out of :mod:`pagebuilder.module` when the module's settings moved into
the database. The wiring here used to run during app construction, from
``register_public_routes`` and ``register_routes`` — phases that finish
*before* the host hydrates a module's settings from the DB. Reading
``content_locales`` there would have meant reading the pydantic default and
mounting one language on a site configured for three.

So it runs from ``on_startup`` instead, which the host calls after hydration.
That is late for mounting routes, and it works for the two reasons this module
depends on:

* ``app.include_router`` before the first request is indistinguishable from
  including it at build time — the router table is consulted per request.
* The public-route registry is published on ``app.state.public_routes`` and
  read live by ``AuthMiddleware``, so a prefix added now is exempt from the
  next request onward.

The cost is that changing any of these values needs a restart, which is what
``requires_restart`` on the fields tells the operator.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from pagebuilder import locales
from pagebuilder.media_files import (
    MediaFiles,
    adopt_legacy_files,
    resolve_media_root,
    warn_on_orphaned_media,
)
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.blobs import BLOBS_DIR, is_digest

_log = logging.getLogger("simple_module.pagebuilder")

_READ_ONLY = frozenset({"GET", "HEAD"})


def dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one "/".

    Public-route rules match with ``str.startswith``, so an unterminated
    prefix leaks into sibling paths that merely share its first characters.
    """
    return f"{prefix.rstrip('/')}/"


def exempt_public_routes(app: FastAPI, settings: PagebuilderSettings) -> None:
    """Exempt the reader-facing surface from authentication.

    Without this the whole point of the module is defeated: ``AuthMiddleware``
    gates every request, so a published page, the sitemap, and robots.txt all
    302 an anonymous visitor to the login screen.

    GET/HEAD only — the admin API lives under a different prefix, but pinning
    the verbs keeps the exemption from widening if a future route adds a POST
    under one of these paths.
    """
    registry = getattr(app.state, "public_routes", None)
    if registry is None:
        # A bare test app, or a host that mounts no auth middleware. Nothing
        # is gating these paths in that case, so there is nothing to exempt.
        return
    methods = set(_READ_ONLY)
    # Trailing slash is load-bearing. These are startswith() prefixes, so a
    # bare "/p" would also exempt "/pagebuilder/" — the entire admin surface.
    #
    # One exemption per content locale, matching the mounts below. Exempting a
    # bare "/{locale}" instead would be shorter and wrong: it would open every
    # path that happens to start with a language tag, admin screens included.
    for locale in settings.content_locales:
        registry.add_prefix(
            dir_prefix(f"{locales.path_prefix(locale)}{settings.public_route_prefix}"),
            methods=methods,
        )
    if len(settings.content_locales) > 1:
        # The default locale's redundant prefix, which 301s to the bare
        # address (see ``default_locale_alias_router``). Exempt too, or the
        # redirect that exists to be forgiving answers with a login page.
        registry.add_prefix(
            dir_prefix(
                f"/{settings.default_content_locale}{settings.public_route_prefix}"
            ),
            methods=methods,
        )
    # Published pages reference uploaded images; without this the page renders
    # for an anonymous visitor but every image 302s to login.
    registry.add_prefix(dir_prefix(settings.media_url_prefix), methods=methods)
    if settings.sitemap_enabled:
        registry.add_exact("/sitemap.xml", methods=methods)
    if settings.robots_enabled:
        registry.add_exact("/robots.txt", methods=methods)


def mount_public_routers(app: FastAPI, settings: PagebuilderSettings) -> None:
    """Mount the public viewer at the host root, one router per language.

    The host's view_router is hard-prefixed with ``view_prefix`` so the public
    viewer can't live there. The default language keeps the bare
    ``{public_route_prefix}/{slug}``; every other one is prefixed with its tag.
    """
    from pagebuilder.endpoints.public_views import (
        default_locale_alias_router,
        locale_router,
    )
    from pagebuilder.endpoints.seo import seo_router

    for locale in settings.content_locales:
        app.include_router(
            locale_router(locale),
            prefix=f"{locales.path_prefix(locale)}{settings.public_route_prefix}",
        )
    if len(settings.content_locales) > 1:
        # Only worth mounting on a multilingual site: with one language there
        # is no /de/p/… for anyone to generalise from, so /en/p/… is just a
        # URL nobody types.
        app.include_router(
            default_locale_alias_router(settings),
            prefix=(
                f"/{settings.default_content_locale}{settings.public_route_prefix}"
            ),
        )
    if settings.sitemap_enabled or settings.robots_enabled:
        # Mounted at the root so crawlers find them where they look.
        app.include_router(seo_router)


async def mount_media(app: FastAPI, settings: PagebuilderSettings) -> None:
    """Serve uploaded files from ``{media_url_prefix}/{tenant_id}/{filename}``.

    Files (and snapshot blobs) written before per-tenant storage sit directly
    under their root; they are moved into the default tenant's directory
    first, so the orphan scan below and every later read find them (#38).
    """
    media_root = resolve_media_root(settings.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    _log.info("pagebuilder.media_root: %s", media_root)
    adopt_legacy_files(media_root)
    adopt_legacy_files(
        resolve_media_root(settings.snapshot_root) / BLOBS_DIR,
        accept=is_digest,
        label="snapshot_blobs",
    )
    app.mount(
        settings.media_url_prefix,
        MediaFiles(directory=media_root),
        name="pagebuilder_media",
    )
    sm = getattr(app.state, "sm", None)
    if sm is not None:
        await warn_on_orphaned_media(sm.db.session_factory, media_root)
