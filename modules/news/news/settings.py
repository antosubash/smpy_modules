"""Deployment-tunable settings for News.

Only the public URL prefix so far. It is a setting rather than a constant
because it is the one thing here a site owner has an opinion about: whether
their articles live at ``/news/…``, ``/blog/…`` or something in their own
language.
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

    Claiming the address means giving it up elsewhere: an article no longer
    answers at ``/p/{slug}`` at all — see ``pagebuilder.public_claims``.
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
    """Where an article serves. One spelling, shared by the serializer and the
    claim news registers with pagebuilder."""
    return f"{active().public_route_prefix.rstrip('/')}/{slug}"
