"""Deployment-tunable settings for News — stored in the database.

The public URL prefix was once the only thing here, because everything else
about serving an article — the origin, the cache policy, the CSP — belonged to
pagebuilder's viewer. News serves its own articles now, so it carries the
settings that viewer needs. They are deliberately the same names and defaults
pagebuilder uses for the equivalent knob: a host running both should not have to
learn two vocabularies to configure one site.

Sourced exactly like :mod:`pagebuilder.settings`: no ``SM_NEWS_*`` env var and
no ``.env`` stanza, just the defaults below and whatever the settings module has
stored. The module registers the class in ``register_settings`` and the host
hydrates it at lifespan start.

A field the module reads *while booting* — where the routers mount, whether the
scheduler runs — is marked ``_RESTART``, because hydration happens after app
construction and changing it later cannot move a router that is already
mounted. Everything else takes effect on save: ``NewsModule`` re-publishes this
module's copy when the Settings screen writes one.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from news import locales

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting."""


class NewsSettings(BaseSettings):
    # ``use_attribute_docstrings`` is what carries the prose below onto the
    # Settings screen, which renders ``FieldInfo.description``.
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
        """Init kwargs only — the hydrator's, or the defaults declared here.

        Dropping the env sources is what makes the Settings screen the whole
        answer: a leftover ``SM_NEWS_*`` in a shell would otherwise outrank a
        value an operator can see, and nothing on screen would say so.
        """
        return (init_settings,)

    public_route_prefix: str = Field(default="/news", json_schema_extra=_RESTART)
    """Where an article serves publicly: ``{prefix}/{slug}``.

    Articles used to share pagebuilder's generic page prefix, so every article
    on the site sat at ``/p/{slug}`` alongside the contact page and the privacy
    notice. The address said nothing about what the document was, and there was
    no way to tell articles apart from pages in a URL, a log line or an
    analytics report.
    """

    public_base_url: str = ""
    """Origin used to build absolute URLs — the canonical tag, ``og:url`` and
    the sitemap.

    Empty means "derive it from the inbound request", which is right for local
    development and wrong behind a proxy that rewrites the Host header. A
    deployment knows its own public name; this is where it says so.
    """

    site_name: str = ""
    """``og:site_name``. Empty omits the tag rather than inventing one."""

    twitter_handle: str = ""
    """``twitter:site``. Empty omits the tag."""

    public_cache_max_age: int = 300
    """Seconds a published article may be held in a shared cache.

    Longer than the listing's minute because an article's *body* changes only
    when someone republishes it, and the ETag catches that case anyway.
    """

    public_cache_swr: int = 60
    """``stale-while-revalidate`` seconds. Zero omits the directive."""

    scheduler_enabled: bool = Field(default=True, json_schema_extra=_RESTART)
    """Run an in-process loop that publishes articles at their scheduled time.

    **Turn this off before you scale the app out.** The loop starts in *every*
    process that boots the module, so ``uvicorn -w 4``, gunicorn with workers,
    or a Deployment with ``replicas > 1`` runs one scheduler per replica.
    ``ArticlesService.process_due`` takes no lock — no ``FOR UPDATE SKIP
    LOCKED``, no advisory lock, nothing that would exist on SQLite anyway — so
    two replicas can find the same due article in the same tick and both publish
    it, leaving two PUBLISH revision rows and, for an unpublish, a flip-flop. A
    single process is the only configuration this default is safe in.

    Multi-replica deployments should set this False everywhere and drive
    ``process_due`` from one place instead — a cron job, a k8s CronJob, a single
    dedicated worker. The same applies where such a worker already exists
    alongside a single app process: both racing gives the same double publish.

    Same name, default and reasoning as pagebuilder's: a host running both
    should not have to learn two vocabularies for one idea.
    """

    scheduler_interval_seconds: int = Field(default=30, json_schema_extra=_RESTART)
    """How often the in-process scheduler looks for articles that are due.

    The granularity of "goes live at": an article scheduled for 09:00 appears
    somewhere in the following interval, never before it. Thirty seconds is
    close enough for an embargo and cheap enough to run on every host.
    """

    public_csp: str = ""
    """Content-Security-Policy for the public article page.

    Empty sends no header, which is the safe default for a module that cannot
    know what a host's other pages already set. A site serving articles as its
    public face should set one.
    """


_active: NewsSettings | None = None


def use(settings: NewsSettings) -> None:
    """Publish the instance the module resolved at startup.

    The public URL appears in ``ArticleRead.url``, which is built by a pure
    serializer with no request to read ``app.state`` from — and the alternative,
    threading the prefix through every read path, would put a settings argument
    on functions that have nothing else to do with configuration.

    Process-global, so it is set once from ``register_settings``, again from
    ``on_startup`` with the hydrated instance, and again whenever the Settings
    screen saves. A test that wants a different prefix calls this and resets it.
    """
    global _active
    _active = settings


def reset() -> None:
    """Forget the published instance. For tests, so one does not leak into the
    next in the same process."""
    global _active
    _active = None


def active() -> NewsSettings:
    """The resolved settings, falling back to the declared defaults.

    The fallback matters for the direct-service tests, which exercise the
    serializer without booting an app to call ``use``.
    """
    global _active
    if _active is None:
        _active = NewsSettings()
    return _active


def public_prefix(locale: str | None = None) -> str:
    """The public route prefix for one language, without a trailing slash.

    ``None`` means the default language, so a caller with no language in hand
    gets exactly the prefix this function always returned.
    """
    prefix = active().public_route_prefix.rstrip("/")
    return f"{locales.path_prefix(locale or locales.default())}{prefix}"


def public_article_path(slug: str, locale: str | None = None) -> str:
    """Where an article serves. One spelling, shared by the serializer, the
    viewer's canonical tag and the sitemap.

    Locale-prefixed for every language but the default one, matching how
    pagebuilder addresses pages: ``/news/{slug}`` is the default language and
    ``/de/news/{slug}`` is German.
    """
    return f"{public_prefix(locale)}/{slug}"


def public_index_path(page: int = 1, locale: str | None = None) -> str:
    """The archive's front page.

    Page 1 has no query string so the index has exactly one canonical address —
    ``/news/`` and ``/news/?page=1`` being two URLs for one page is how an
    archive ends up competing with itself in an index.
    """
    root = f"{public_prefix(locale)}/"
    return root if page <= 1 else f"{root}?page={page}"


def public_category_path(slug: str, locale: str | None = None) -> str:
    """A category's archive. Two segments, so it cannot collide with an article
    slug — the article route matches a single segment."""
    return f"{public_prefix(locale)}/category/{slug}"


def public_tag_path(slug: str, locale: str | None = None) -> str:
    return f"{public_prefix(locale)}/tag/{slug}"


def public_feed_path(locale: str | None = None) -> str:
    """The RSS feed. ``feed.xml`` rather than ``rss.xml`` because the same
    address should keep working if the format is ever changed for Atom."""
    return f"{public_prefix(locale)}/feed.xml"
