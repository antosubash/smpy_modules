"""The settings the module reads once, while booting — every ``requires_restart``
field of :class:`~sm_records.settings.RecordsSettings`, as its base class.

Split from ``settings.py`` for the 300-line cap, along the one seam that means
something: everything declared here is consumed from ``on_startup`` (a route
mounted, an exemption registered, a media backend chosen) or changes what the
install *publishes*, so an edit on the Settings screen takes effect at the next
boot and is marked ``requires_restart``. Everything declared on the subclass is
read per request.

A base class and not a mixin: pydantic collects fields and validators only
from ``BaseModel`` subclasses, and ``use_attribute_docstrings`` applies where a
field is declared — so the config is repeated here, or the Settings screen
would show these four with no explanation. Fields of a base class come first
in ``model_fields``, which is the order they were declared in before the split.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sm_records import constants
from sm_records.settings_checks import (
    DEFAULT_PUBLIC_ROUTE_PREFIX,
    StoredSourcesOnly,
    check_content_locales,
    check_media_api_prefix,
    check_public_route_prefix,
)

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See the module docstring."""


class BootSettings(StoredSourcesOnly, BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    public_route_prefix: str = Field(
        default=DEFAULT_PUBLIC_ROUTE_PREFIX, json_schema_extra=_RESTART
    )
    """URL prefix for the anonymous read API of public record types.

    ``GET {prefix}/{type_key}`` and ``GET {prefix}/{type_key}/{uuid}`` serve the
    published records of a type whose ``is_public`` is set, to callers with no
    session at all (design §10). A type that is not public is a 404 on both,
    indistinguishable from one that does not exist.

    Read once, while booting: :mod:`sm_records.boot` mounts the router and
    exempts the prefix from ``AuthMiddleware`` from ``on_startup``, so a new
    value needs a restart — which is what ``requires_restart`` tells the
    operator. The exemption is a prefix rule terminating in ``/``, so a value
    sharing its first characters with the admin API (``/api/records``) is still
    safe; a value that is a *parent* of it — or of ``/admin`` — is refused by
    :func:`check_public_route_prefix`, as are ``/`` and a value with no leading
    slash.
    """

    content_locales: tuple[str, ...] = Field(
        default=(constants.DEFAULT_CONTENT_LOCALE,), json_schema_extra=_RESTART
    )
    """Languages a record may be authored in (Phase 5 §4.2).

    Edited on the Settings screen as a JSON array — ``["en","de","fr"]``. A
    single entry (the default) is what a monolingual install runs on and costs
    it nothing: every record is in that locale, no type is translatable, and the
    public API behaves as it did before there was such a thing as a language.

    **Deliberately this module's own setting and not pagebuilder's.**
    ``records`` must not depend on ``pagebuilder`` — it is published on its own
    and a host may install either without the other — and the two may
    legitimately publish in different language sets. A host that wants them
    aligned sets both; the README says so. Distinct again from the host's
    ``SM_I18N_SUPPORTED_LOCALES``, which decides what the *admin console*
    speaks rather than what the content is published in.
    """

    default_content_locale: str = Field(
        default=constants.DEFAULT_CONTENT_LOCALE, json_schema_extra=_RESTART
    )
    """The locale a record is in when the caller does not say.

    Also the only locale a type that is not ``translatable`` accepts, and what
    ``?locale=`` defaults to on the anonymous read API — absent means *this
    language*, never "all", because an anonymous reader is asking for one site
    (§4.4).

    Must appear in :attr:`content_locales`; a mismatch is refused here rather
    than 404ing every public read at the first request.
    """

    media_api_prefix: str | None = Field(default=None, json_schema_extra=_RESTART)
    """Where the media library's JSON API lives, for the ``media`` field picker.

    ``null`` (the default) detects it: at startup the module looks for the
    framework ``file_storage`` module's routes on this app — ``POST
    {prefix}/upload``, ``GET {prefix}/files``, ``GET {prefix}/files/{id}`` and
    ``GET {prefix}/files/{id}/download`` — and uses their prefix
    (``/api/file-storage`` on a stock host). No match means no picker: a
    ``media`` field stays the plain text box it always was.

    A path (``"/api/file-storage"``) skips detection and uses that prefix; an
    empty string (``""``) turns the picker off on a host that has a media
    library. Edited as JSON on the Settings screen, because the value has three
    states: ``null``, ``""`` or a quoted path.

    Must be a path on *this* host — the browser calls it with the session
    cookie, directly, and the media module's own permissions decide what the
    caller may list, upload or read. Read once, while booting.
    """

    @field_validator("public_route_prefix")
    @classmethod
    def _check_prefix(cls, value: str) -> str:
        """Refuse a prefix that would exempt the admin surface — or the whole
        host — from ``AuthMiddleware``. See :func:`check_public_route_prefix`."""
        return check_public_route_prefix(value)

    @field_validator("media_api_prefix")
    @classmethod
    def _check_media_prefix(cls, value: str | None) -> str | None:
        """A root-relative path or one of the two sentinels — see
        :func:`~sm_records.settings_checks.check_media_api_prefix`."""
        return check_media_api_prefix(value)

    @model_validator(mode="after")
    def _check_locales(self) -> BootSettings:
        """The three rules :mod:`sm_records.locales` then takes for granted —
        see :func:`~sm_records.settings_checks.check_content_locales`."""
        check_content_locales(self.content_locales, self.default_content_locale)
        return self
