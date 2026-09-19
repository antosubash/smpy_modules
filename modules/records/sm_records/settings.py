"""Records module settings — stored in the database, edited in Settings.

Follows :mod:`pagebuilder.settings` exactly: there is no ``SM_RECORDS_*``
environment variable and no ``.env`` stanza. ``settings_customise_sources``
drops every source pydantic-settings would otherwise consult, leaving the
field defaults below and whatever the settings module has stored. The module
registers this class in ``register_settings`` via ``register_module_settings``,
the host hydrates it from the DB at lifespan start, and the Settings screen
writes it back.

``public_route_prefix`` is read at boot to mount the anonymous read routes
(design doc §10), so it carries ``requires_restart`` — the Settings screen
surfaces that next to the input. Everything else here is read per request and
takes effect on save.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See the module docstring."""


class RecordsSettings(BaseSettings):
    # ``use_attribute_docstrings`` puts the prose under each field on the
    # Settings screen: the admin UI renders ``FieldInfo.description``, and
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
        the default declared here. Dropping the env sources rather than
        merely not documenting them is deliberate — a stray
        ``SM_RECORDS_*`` left in a shell or a deploy manifest would
        otherwise quietly outrank the value an operator can see and edit on
        the Settings screen.
        """
        return (init_settings,)

    public_route_prefix: str = Field(default="/api/records/public", json_schema_extra=_RESTART)
    """URL prefix for the anonymous read API of public record types.

    Mounted via ``register_public_routes`` from ``on_startup`` (design doc
    §10), because the set of public types is only known after settings
    hydration. Changing the prefix remounts those routes, so it takes effect
    on restart.
    """

    default_page_size: int = 25
    """Default page size for a list endpoint that receives no explicit
    ``limit``."""

    max_page_size: int = 200
    """Largest ``limit`` a caller may request on a list endpoint. Must be at
    least :attr:`default_page_size`."""

    revision_limit: int = 50
    """How many ``records_revision`` rows are kept per record.

    Append-only revisions are cheap insurance against a bad edit, but
    unbounded on a busy type they outgrow the document table itself — the
    oldest revisions beyond this count are pruned on write.
    """

    max_payload_bytes: int = 262144
    """Reject a record write whose ``data`` payload, serialized, exceeds this
    many bytes (default 256 KB)."""

    max_fields_per_type: int = 100
    """Largest number of field definitions a single Record Type may declare."""

    max_indexed_fields_per_type: int = 25
    """Largest number of *indexed* field definitions a single Record Type may
    declare. Must not exceed :attr:`max_fields_per_type`.

    Easy to omit and expensive to add later: every indexed field is a row
    written per record per save, so a type with 80 indexed fields turns one
    save into 81 inserts. A visible ceiling makes that a design conversation
    at schema-editing time instead of an incident.
    """

    reindex_batch_size: int = 500
    """Number of records processed per batch by the reindex command and by a
    schema-triggered index-table migration (design doc §8.5)."""

    reindex_stale_after_seconds: int = 900
    """A ``reindex_pending`` entry (design doc §8.5) older than this degrades
    ``/health/ready`` and names the type and field (default 15 minutes).

    Turns an orphaned reindex — one whose background task died with the
    worker that owned it — from a support ticket into an alert.
    """

    @model_validator(mode="after")
    def _check_limits(self) -> RecordsSettings:
        if self.default_page_size > self.max_page_size:
            raise ValueError(
                f"default_page_size ({self.default_page_size}) must not exceed "
                f"max_page_size ({self.max_page_size})"
            )
        if self.max_indexed_fields_per_type > self.max_fields_per_type:
            raise ValueError(
                f"max_indexed_fields_per_type ({self.max_indexed_fields_per_type}) "
                f"must not exceed max_fields_per_type ({self.max_fields_per_type})"
            )
        return self
