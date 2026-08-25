"""Deployment-tunable settings for News.

The public URL prefix was once the only thing here, because everything else
about serving an article — the origin, the cache policy, the CSP — belonged to
pagebuilder's viewer. News serves its own articles now, so it carries the
settings that viewer needs. They are deliberately the same names and defaults
pagebuilder uses for the equivalent knob: a host running both should not have to
learn two vocabularies to configure one site.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class NewsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_NEWS_", extra="ignore")

    public_route_prefix: str = "/news"
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

    Process-global, so it is set once from ``register_settings`` and read
    everywhere. A test that wants a different prefix calls this and resets it.
    """
    global _active
    _active = settings


def reset() -> None:
    """Forget the published instance. For tests, so one does not leak into the
    next in the same process."""
    global _active
    _active = None


def active() -> NewsSettings:
    """The resolved settings, falling back to the environment.

    The fallback matters for the direct-service tests, which exercise the
    serializer without booting an app to call ``use``.
    """
    global _active
    if _active is None:
        _active = NewsSettings()
    return _active


def public_article_path(slug: str) -> str:
    """Where an article serves. One spelling, shared by the serializer, the
    viewer's canonical tag and the sitemap."""
    return f"{active().public_route_prefix.rstrip('/')}/{slug}"
