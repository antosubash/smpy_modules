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
from urllib.parse import quote

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

    Safe to leave on when the app is scaled out. The loop still starts in
    *every* process that boots the module — ``uvicorn -w 4``, gunicorn with
    workers, a Deployment with ``replicas > 1`` — but ``process_due`` now claims
    each due article with a single conditional ``UPDATE`` before it touches it,
    so exactly one replica flips it: one PUBLISH revision row, and no flip-flop
    on the way back down. An external worker driving ``process_due`` on its own
    schedule is safe alongside the loop for the same reason. See
    ``news.content._claims`` for the shape and its limits.

    Two things the claim does not do. It does not stop N replicas each polling
    the database every ``scheduler_interval_seconds``; where that traffic is
    unwanted, set this False everywhere and drive ``process_due`` from one place
    — a cron job, a k8s CronJob, a dedicated worker. And it does not make the
    replicas' clocks agree: each tick asks its own ``now``, so an article goes
    live when the *first* replica to think it due acts, which a badly skewed
    clock moves by that skew. That was already true of the poll interval, and it
    is why the claim itself depends on no clock — it settles who acts, never
    when.

    Turn it off from the Settings screen or with
    ``scripts/set_setting.py news scheduler_enabled false``, never an
    environment variable: this module reads none, so an
    ``SM_NEWS_SCHEDULER_ENABLED`` in a deploy manifest would leave the loop
    running with nothing on screen saying so.

    Same name and default as pagebuilder's, so a host running both does not have
    to learn two vocabularies for one idea — but not the same guarantee.
    Pagebuilder's loop takes no claim and is still single-process only.
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
    """A tag's archive. The slug may be non-ASCII, so it is percent-encoded:
    sitemaps, ``hreflang`` and canonical links want an RFC 3986 address."""
    return f"{public_prefix(locale)}/tag/{quote(slug, safe='')}"


def public_author_path(slug: str, locale: str | None = None) -> str:
    """A byline's archive.

    Two segments, like a category's, so it cannot collide with an article slug.
    The slug is *derived* from the byline rather than read off a row — there is
    no author table; see :mod:`news.authors` for why not.
    """
    return f"{public_prefix(locale)}/author/{slug}"


def public_feed_path(locale: str | None = None) -> str:
    """The RSS feed. ``feed.xml`` rather than ``rss.xml`` because the same
    address should keep working if the format is ever changed for Atom."""
    return f"{public_prefix(locale)}/feed.xml"
