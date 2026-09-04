"""Deployment-tunable settings for News — stored in the database.

Only the public URL prefix so far. It is a setting rather than a constant
because it is the one thing here a site owner has an opinion about: whether
their articles live at ``/news/…``, ``/blog/…`` or something in their own
language.

Sourced exactly like :mod:`pagebuilder.settings`: no ``SM_NEWS_*`` env var and
no ``.env`` stanza, just the default below and whatever the settings module has
stored. The module registers the class in ``register_settings`` and the host
hydrates it at lifespan start.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from news.integrations.locales import default_locale, locale_path_prefix

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


def public_article_path(slug: str, locale: str | None = None) -> str:
    """Where an article serves. One spelling, shared by the serializer and the
    claim news registers with pagebuilder.

    Locale-prefixed for every language but the default one, matching how
    pagebuilder addresses pages: ``/news/{slug}`` is the default language and
    ``/de/news/{slug}`` is German. ``None`` means the default, so a caller with
    no language in hand gets exactly the URL this function always returned.
    """
    prefix = locale_path_prefix(locale or default_locale())
    return f"{prefix}{active().public_route_prefix.rstrip('/')}/{slug}"
