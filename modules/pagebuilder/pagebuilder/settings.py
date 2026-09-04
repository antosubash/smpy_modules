"""PageBuilder module settings — stored in the database, edited in Settings.

There is no ``SM_PAGEBUILDER_*`` environment variable and no ``.env`` stanza:
:meth:`settings_customise_sources` drops every source pydantic-settings would
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

from pathlib import Path
from typing import Any, Final

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See the module docstring."""


class PagebuilderSettings(BaseSettings):
    # ``use_attribute_docstrings`` is what puts the prose under each field on
    # the Settings screen: the admin UI renders ``FieldInfo.description``, and
    # without this every field would arrive there unexplained while the
    # explanation sat in the source three lines below it.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Init kwargs only — no env, no ``.env``, no secrets directory.

        The hydrator passes stored overrides as keyword arguments, so this
        leaves exactly two answers for any field: what the database says, or
        the default declared here. Dropping the env sources rather than merely
        not documenting them is deliberate — a stray ``SM_PAGEBUILDER_*`` left
        in a shell or a deploy manifest would otherwise quietly outrank the
        value an operator can see and edit on the Settings screen.
        """
        return (init_settings,)

    public_route_prefix: str = Field(default="/p", json_schema_extra=_RESTART)
    """URL prefix used for public published pages: ``{prefix}/{slug}``."""

    content_locales: tuple[str, ...] = Field(default=("en",), json_schema_extra=_RESTART)
    """Languages a page may be authored in.

    Distinct from the host's ``SM_I18N_SUPPORTED_LOCALES``, which decides what
    language the *admin console* speaks. A site can translate its content
    without translating its console, or the reverse, so the two are configured
    separately — see :mod:`pagebuilder.locales`.

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

    media_root: Path = Field(
        default=Path("var/pagebuilder/media"), json_schema_extra=_RESTART
    )
    """Filesystem directory where uploaded media is stored.

    Relative paths are anchored to the project root (``SM_PROJECT_ROOT``
    when set, else the nearest directory holding a ``pyproject.toml``,
    ``.env`` or ``alembic.ini``) — never the bare process cwd, which made
    two differently-launched processes read and write different media
    directories against one database. Created if it doesn't exist.
    """

    media_url_prefix: str = Field(
        default="/media/pagebuilder", json_schema_extra=_RESTART
    )
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
    should add it explicitly on the Settings screen and pair it with their
    own sanitizer.
    """

    media_thumbnail_widths: tuple[int, ...] = (320, 640, 1280, 1920)
    """Pixel widths to generate webp thumbnails for on upload.

    Only widths *strictly less than* the source width produce a derivative
    — there's no point upscaling a 600px hero to 1920px. Set to an empty
    tuple to disable thumbnail generation entirely.
    """

    media_webp_quality: int = 82
    """Pillow encoder ``quality`` for webp thumbnails (0-100)."""

    snapshot_root: Path = Path("var/pagebuilder/snapshots")
    """Filesystem directory holding content snapshots and their shared blobs.

    Anchored to the project root exactly like :attr:`media_root`. A
    cwd-relative default is what made two differently-launched processes
    read and write different media directories against one database
    (issue #14); snapshots would fail the same way, and more quietly.
    """

    snapshot_max_upload_bytes: int = 200 * 1024 * 1024
    """Reject uploaded bundles larger than this (default 200 MB).

    Far larger than ``media_max_bytes`` because a bundle legitimately
    contains a whole media library, not one image.
    """

    snapshot_max_extracted_bytes: int = 1024 * 1024 * 1024
    """Reject a bundle that expands to more than this (default 1 GB).

    Separate from ``snapshot_max_upload_bytes`` because the compressed size
    bounds nothing: a bundle's media is already-compressed images that barely
    shrink, but a crafted archive of repetitive bytes reaches roughly 1000:1,
    so a body inside the upload cap can still fill the disk on extraction.
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

    The token is per-session, generated lazily on the first admin GET and
    surfaced both via Inertia shared props (``csrf.token``) and a
    non-``HttpOnly`` cookie (see ``csrf_cookie_name``) so the React client
    can read it back and include it on every POST/PUT/PATCH/DELETE.
    """

    csrf_cookie_name: str = "pagebuilder_csrf"
    """Cookie name used to expose the per-session CSRF token to JS."""

    scheduler_enabled: bool = Field(default=True, json_schema_extra=_RESTART)
    """Run an in-process loop that flips pages on their scheduled times.

    Disable in deployments where a separate worker (Celery beat, k8s
    CronJob, etc.) drives :meth:`PagesService.process_due` directly —
    otherwise both would race and double-publish.
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
