"""PageBuilder module settings — stored in the database, edited in Settings.

There is no ``SM_PAGEBUILDER_*`` environment variable and no ``.env`` stanza:
``DbBackedSettings`` drops every source pydantic-settings would
otherwise consult, leaving the field defaults below and whatever the settings
module has stored. The module registers this class in ``register_settings``
via ``register_module_settings``, the host hydrates it from the DB at lifespan
start, and the Settings screen writes it back.

One place to look is the point. Configuration split between a ``.env`` file,
the real environment and a database is configuration nobody can read off a
running system — and the two that are not the database are invisible to the
screen that claims to show what the site is configured to do.

Fields the module consumes at boot — the ones that decide route topology, what
is mounted, and what the auth layer exempts — carry ``requires_restart``, which
the Settings screen surfaces next to the input. Everything else is read per
request and takes effect on save.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from pagebuilder.core.settings_media import _RESTART, MediaSettings


class PagebuilderSettings(MediaSettings):
    """Every pagebuilder setting; the media and snapshot ones are :class:`MediaSettings`'.

    The model config and ``DbBackedSettings``' source rule (database and
    defaults only, never the environment) are inherited from there too.
    """

    public_route_prefix: str = Field(default="/p", json_schema_extra=_RESTART)
    """URL prefix used for public published pages: ``{prefix}/{slug}``."""

    content_locales: tuple[str, ...] = Field(default=("en",), json_schema_extra=_RESTART)
    """Languages a page may be authored in.

    Distinct from the host's ``SM_I18N_SUPPORTED_LOCALES``, which decides what
    language the *admin console* speaks. A site can translate its content
    without translating its console, or the reverse, so the two are configured
    separately — see :mod:`pagebuilder.core.locales`.

    Edited on the Settings screen as a JSON array — ``["en","de","fr"]``.
    A single entry (the default) leaves every public URL exactly as it was, so
    this feature costs a monolingual site nothing. Adding or removing a
    language remounts the public routes, so it takes effect on restart.
    """

    default_content_locale: str = Field(default="en", json_schema_extra=_RESTART)
    """The locale served at the *unprefixed* public URL.

    ``/p/{slug}`` is this language; every other one is ``/{locale}/p/{slug}``.
    Keeping the default unprefixed is what lets a site that already has pages
    add a second language without rewriting a single address — and
    ``/{default}/p/{slug}`` permanently redirects to the bare form so one
    document never answers at two URLs.

    Must appear in ``content_locales``; a mismatch fails at boot rather than
    404ing the entire site at the first request.
    """

    public_csp: str = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https: data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    """Content-Security-Policy header value for ``/p/{slug}`` responses.

    Widen it on the Settings screen for analytics, fonts, CDNs, etc. Set to
    an empty string to disable. Read per response, so a change is live on
    save.
    """

    public_cache_max_age: int = 60
    """``max-age`` (seconds) on ``Cache-Control`` for published pages."""

    public_cache_swr: int = 600
    """``stale-while-revalidate`` (seconds) on published pages."""

    public_base_url: str | None = None
    """Absolute base URL of the public site (e.g. ``https://example.com``).

    Used to build canonical / ``og:url`` values. When unset, a single-tenant
    host uses the host's own ``public_base_url``; with both blank the public
    page falls back to ``Request.url`` — fine for local dev but unreliable
    behind a reverse proxy that strips ``Host`` / ``X-Forwarded-*``
    headers. No trailing slash; the public route prefix is appended.
    """

    site_name: str | None = None
    """Brand name emitted as ``<meta property="og:site_name">``.

    Skip the tag entirely when blank — empty meta tags hurt social-card
    previews more than missing ones.
    """

    twitter_handle: str | None = None
    """Publisher handle emitted as ``<meta name="twitter:site">``.

    Include the leading ``@``; rendered verbatim so consumers (Twitter's
    crawler, link unfurlers) see exactly what's configured. Skipped when
    blank.
    """

    sitemap_enabled: bool = Field(default=True, json_schema_extra=_RESTART)
    """Serve ``GET /sitemap.xml`` listing all published, indexable pages.

    Disable when the host already publishes its own sitemap (e.g. a
    multi-module deployment whose top-level sitemap aggregates several
    sources).
    """

    robots_enabled: bool = Field(default=True, json_schema_extra=_RESTART)
    """Serve ``GET /robots.txt`` referencing the sitemap when enabled."""

    robots_body: str | None = None
    """Override the default ``robots.txt`` body.

    When ``None``, the route emits a minimal ``User-agent: *\nAllow: /``
    plus a ``Sitemap:`` reference (only when ``sitemap_enabled``). Set
    explicitly to lock crawlers out of a staging environment.
    """

    seo_cache_max_age: int = 300
    """``max-age`` (seconds) on the ``Cache-Control`` header for
    ``/sitemap.xml`` and ``/robots.txt``."""

    requires_auth: bool = True
    """Gate admin routes (``/pagebuilder/*`` and ``/api/pagebuilder/*``)
    behind a ``get_current_user`` dependency.

    Defaults to ``True`` so a host scaffolded without auth middleware does
    not silently expose page CRUD + media uploads to the public internet.
    The public viewer (``/p/{slug}``) is always anonymous regardless of
    this setting. Turn it off only when the host gates admin paths at a
    layer above the application (e.g. an authenticating reverse proxy).

    Evaluated per request rather than when the routers are built, so it takes
    effect on save — the alternative is a switch the Settings screen offers
    and the running app ignores until someone restarts it.
    """

    csrf_protect: bool = True
    """Require an ``X-CSRF-Token`` header on every mutating admin request.

    The check and the token are the framework's (``simple_module_hosting.csrf``),
    the same ones billing, news and records use. The framework shares the
    token with every signed-in page as the ``csrfToken`` prop, and the React client
    sends it back on every POST/PUT/PATCH/DELETE. Turn it off only when the
    host guards writes at a layer above the application.
    """

    scheduler_enabled: bool = Field(default=True, json_schema_extra=_RESTART)
    """Run an in-process loop that flips pages on their scheduled times.

    Safe to leave on in every process: ``process_due`` claims each due page
    with a conditional ``UPDATE`` before flipping it, so replicas (or an
    external worker driving :meth:`PagesService.process_due` alongside) flip
    a page once. Disable where a deployment would rather one place polled
    (Celery beat, k8s CronJob, etc.).
    """

    scheduler_interval_seconds: int = Field(default=30, json_schema_extra=_RESTART)
    """How often the in-process scheduler wakes to look for due flips."""

    @model_validator(mode="after")
    def _check_locales(self) -> PagebuilderSettings:
        if not self.content_locales:
            raise ValueError("content_locales must list at least one locale")
        if self.default_content_locale not in self.content_locales:
            raise ValueError(
                f"default_content_locale {self.default_content_locale!r} is not in "
                f"content_locales {list(self.content_locales)}"
            )
        return self
