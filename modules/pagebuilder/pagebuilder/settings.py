"""PageBuilder module settings.

Per-module env-var prefix is ``SM_PAGEBUILDER_*``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PagebuilderSettings(BaseSettings):
    # ``env_file`` mirrors the host's own BootstrapSettings (and sm_ai's
    # settings): pydantic-settings reads the file itself rather than exporting
    # it, so a module that omits this only ever sees real environment
    # variables — and every ``SM_PAGEBUILDER_*`` line in the repo's root
    # ``.env``, which CLAUDE.md calls the single source of truth for settings,
    # would be silently ignored.
    model_config = SettingsConfigDict(
        env_prefix="SM_PAGEBUILDER_", env_file=".env", extra="ignore"
    )

    public_route_prefix: str = "/p"
    """URL prefix used for public published pages: ``{prefix}/{slug}``."""

    content_locales: tuple[str, ...] = ("en",)
    """Languages a page may be authored in.

    Distinct from the host's ``SM_I18N_SUPPORTED_LOCALES``, which decides what
    language the *admin console* speaks. A site can translate its content
    without translating its console, or the reverse, so the two are configured
    separately — see :mod:`pagebuilder.locales`.

    Set as a JSON array: ``SM_PAGEBUILDER_CONTENT_LOCALES='["en","de","fr"]'``.
    A single-entry tuple (the default) leaves every public URL exactly as it
    was, so this feature costs a monolingual site nothing.
    """

    default_content_locale: str = "en"
    """The locale served at the *unprefixed* public URL.

    ``/p/{slug}`` is this language; every other one is ``/{locale}/p/{slug}``.
    Keeping the default unprefixed is what lets a site that already has pages
    add a second language without rewriting a single address — and
    ``/{default}/p/{slug}`` permanently redirects to the bare form so one
    document never answers at two URLs.

    Must appear in ``content_locales``; a mismatch fails at boot rather than
    404ing the entire site at the first request.
    """

    media_root: Path = Path("var/pagebuilder/media")
    """Filesystem directory where uploaded media is stored.

    Relative paths are anchored to the project root (``SM_PROJECT_ROOT``
    when set, else the nearest directory holding a ``pyproject.toml``,
    ``.env`` or ``alembic.ini``) — never the bare process cwd, which made
    two differently-launched processes read and write different media
    directories against one database. Created if it doesn't exist.
    """

    media_url_prefix: str = "/media/pagebuilder"
    """URL prefix the media directory is mounted at."""

    media_max_bytes: int = 10 * 1024 * 1024
    """Reject uploads larger than this (default 10 MB)."""

    media_allowed_content_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    )
    """Content-types accepted by the upload endpoint.

    SVG is intentionally excluded from the default allowlist: SVG is XML
    and can embed ``<script>`` tags, yielding stored-XSS the moment a
    user views the file under a same-origin URL. Hosts that need SVG
    should add it explicitly via ``SM_PAGEBUILDER_MEDIA_ALLOWED_CONTENT_TYPES``
    and pair it with their own sanitizer.
    """

    media_thumbnail_widths: tuple[int, ...] = (320, 640, 1280, 1920)
    """Pixel widths to generate webp thumbnails for on upload.

    Only widths *strictly less than* the source width produce a derivative
    — there's no point upscaling a 600px hero to 1920px. Set to an empty
    tuple to disable thumbnail generation entirely.
    """

    media_webp_quality: int = 82
    """Pillow encoder ``quality`` for webp thumbnails (0-100)."""

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

    Override via ``SM_PAGEBUILDER_PUBLIC_CSP`` to widen for analytics,
    fonts, CDNs, etc. Set to an empty string to disable.
    """

    public_cache_max_age: int = 60
    """``max-age`` (seconds) on ``Cache-Control`` for published pages."""

    public_cache_swr: int = 600
    """``stale-while-revalidate`` (seconds) on published pages."""

    public_base_url: str | None = None
    """Absolute base URL of the public site (e.g. ``https://example.com``).

    Used to build canonical / ``og:url`` values. When unset, the public
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

    sitemap_enabled: bool = True
    """Serve ``GET /sitemap.xml`` listing all published, indexable pages.

    Disable when the host already publishes its own sitemap (e.g. a
    multi-module deployment whose top-level sitemap aggregates several
    sources).
    """

    robots_enabled: bool = True
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
    this setting. Disable via ``SM_PAGEBUILDER_REQUIRES_AUTH=false`` only
    when the host gates admin paths at a layer above the application
    (e.g. an authenticating reverse proxy).
    """

    csrf_protect: bool = True
    """Require an ``X-CSRF-Token`` header on every mutating admin request.

    The token is per-session, generated lazily on the first admin GET and
    surfaced both via Inertia shared props (``csrf.token``) and a
    non-``HttpOnly`` cookie (see ``csrf_cookie_name``) so the React client
    can read it back and include it on every POST/PUT/PATCH/DELETE.
    """

    csrf_cookie_name: str = "pagebuilder_csrf"
    """Cookie name used to expose the per-session CSRF token to JS."""

    scheduler_enabled: bool = True
    """Run an in-process loop that flips pages on their scheduled times.

    Disable in deployments where a separate worker (Celery beat, k8s
    CronJob, etc.) drives :meth:`PagesService.process_due` directly —
    otherwise both would race and double-publish.
    """

    scheduler_interval_seconds: int = 30
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
