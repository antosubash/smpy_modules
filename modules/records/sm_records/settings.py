"""Records module settings — stored in the database, edited in Settings.

Follows :mod:`pagebuilder.settings` exactly: there is no ``SM_RECORDS_*``
environment variable and no ``.env`` stanza. ``settings_customise_sources``
drops every source pydantic-settings would otherwise consult, leaving the
field defaults below and whatever the settings module has stored. The module
registers this class in ``register_settings`` via ``register_module_settings``,
the host hydrates it from the DB at lifespan start, and the Settings screen
writes it back.

``public_route_prefix`` carries ``requires_restart`` because the anonymous
read routes it configures are mounted from ``on_startup`` — after hydration,
which is the only point at which the prefix is known, and long after the
router table would otherwise be built (see :mod:`sm_records.boot`). Changing
it therefore takes a restart. Everything else here is read per request and
takes effect on save.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from sm_records import constants

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting. See the module docstring."""

DEFAULT_PUBLIC_ROUTE_PREFIX: Final = "/api/records/public"
"""Where the anonymous read API lives unless an operator moves it. Named
because :mod:`sm_records.boot` falls back to it for a stored value that does
not validate — see :func:`check_public_route_prefix`."""

_FORBIDDEN_PREFIXES: Final = (
    constants.ROUTE_PREFIX_API,
    constants.VIEW_PREFIX,
    "/api",
    "/admin",
)
"""Paths the anonymous exemption may not cover. The rule is *ancestry*, not
equality: the exemption is a ``startswith`` over a prefix terminating in
``/``, so a value that is a parent of any of these hands every ``GET`` under
it to anonymous callers — ``AuthMiddleware`` is disabled for the whole
subtree, other modules' routes included."""


def check_public_route_prefix(value: str) -> str:
    """The rule :attr:`RecordsSettings.public_route_prefix` must satisfy.

    A function rather than only a validator body because :mod:`sm_records.boot`
    needs the same answer about a value that reached it anyway — a row stored
    before this rule existed — without a pydantic exception and without
    taking the host down at ``on_startup``.

    Three refusals, each with a failure mode behind it: a value with no
    leading ``/`` made ``PublicRouteRegistry.add_prefix`` assert and killed
    the lifespan, leaving the setting editable only through the app that
    would not start; ``/`` (or an empty value, which normalises to it)
    exempted every ``GET`` in the host; and a parent of the admin API or the
    admin views exempted those. Anything *under* the admin API's prefix is
    fine — the exemption cannot reach upwards.
    """
    if not value.startswith("/"):
        raise ValueError("must start with '/'")
    trimmed = value.rstrip("/")
    if not trimmed:
        raise ValueError("must name at least one path segment, so it cannot be '/'")
    for reserved in _FORBIDDEN_PREFIXES:
        if reserved == trimmed or reserved.startswith(f"{trimmed}/"):
            raise ValueError(
                f"{value!r} is {reserved!r} or a parent of it, so exempting it from "
                "authentication would expose the admin surface to anonymous callers"
            )
    return value


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

    public_route_prefix: str = Field(
        default=DEFAULT_PUBLIC_ROUTE_PREFIX, json_schema_extra=_RESTART
    )
    """URL prefix for the anonymous read API of public record types.

    ``GET {prefix}/{type_key}`` and ``GET {prefix}/{type_key}/{uuid}`` serve
    the published records of a type whose ``is_public`` is set, to callers
    with no session at all (design §10). A type that is not public is a 404
    on both, indistinguishable from one that does not exist.

    Read once, while booting: :mod:`sm_records.boot` mounts the router and
    exempts the prefix from ``AuthMiddleware`` from ``on_startup``, so a new
    value needs a restart — which is what ``requires_restart`` tells the
    operator on the Settings screen. The exemption is registered as a prefix
    rule terminating in ``/``; a value sharing its first characters with the
    admin API (``/api/records``) is therefore still safe, and a value that is
    a *parent* of it — or of ``/admin`` — is refused outright by
    :func:`check_public_route_prefix`, as are ``/`` and a value with no
    leading slash.
    """

    default_page_size: int = 25
    """Default page size for a list endpoint that receives no explicit
    ``limit``."""

    max_page_size: int = 200
    """Largest ``limit`` a caller may request on a list endpoint. Must be at
    least :attr:`default_page_size`."""

    revision_limit: int = Field(default=50, ge=1)
    """How many ``records_revision`` rows are kept per record.

    Append-only revisions are cheap insurance against a bad edit, but
    unbounded on a busy type they outgrow the document table itself — the
    oldest revisions beyond this count are pruned on write.

    At least 1: there is no "unlimited" setting, and ``0`` — which an operator
    would read as "keep no history" — is not representable rather than
    silently meaning the opposite. Every write appends a revision, so a limit
    of 1 keeps exactly the current one.
    """

    max_payload_bytes: int = 262144
    """Reject a record write whose ``data`` payload, serialized, exceeds this
    many bytes (default 256 KB)."""

    max_import_bytes: int = 52428800
    """Reject an import whose uploaded body exceeds this many bytes (default
    50 MB), before it is parsed.

    Checked against ``Content-Length`` first and then against what was
    actually read, because a chunked request carries no length header and a
    lying one is not a reason to buffer 4 GB of CSV into memory. The ceiling
    is on the *file*, not on the records in it: a row that is individually too
    big is still refused by :attr:`max_payload_bytes` on its own write.
    """

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

    max_count: int = Field(default=10000, ge=1)
    """How far a list page's ``total`` is counted exactly before it is capped.

    A page can stop after ``page_size`` matches; the ``COUNT`` behind ``total``
    never can, so an unbounded one is O(matches) on a request whose page is
    O(25) — the cost of a filter that matches most of a large type, paid on
    every page of it. The count is bounded to ``max_count + 1`` rows instead:
    at or below the ceiling ``total`` is the exact number and ``total_capped``
    is ``false``, above it ``total`` is ``max_count`` and ``total_capped`` is
    ``true``, which the list screen renders as "10,000+".

    A caller that pages with ``?after=`` and does not need the number at all
    should send ``?total=false`` and skip the statement entirely.
    """

    preview_sync_limit: int = Field(default=5000, ge=0)
    """Largest type ``POST /types/{key}/schema/preview`` will dry-run inside
    the request (design §8.9).

    A dry run validates every record of the type, trash included, at roughly a
    thousand records a second — fine for a small type and a multi-minute HTTP
    request for a large one, with whatever proxy timeout that implies. Above
    this many records the endpoint answers ``202`` with a job id and runs the
    scan through the module's deferred-job mechanism; the caller polls
    ``GET /types/{key}/schema/preview/{job}``.

    ``0`` sends every preview through the job, which is the setting to reach
    for behind a proxy with a short timeout.
    """

    preview_job_ttl_seconds: int = Field(default=600, ge=0)
    """How long a finished preview job's report stays reusable.

    Two things read it: the job registry prunes anything older, and ``PUT
    /types/{key}`` reuses a completed job's report instead of re-running the
    scan inline when the job was taken against the same type, the same
    proposed fields and the same ``RecordType.version`` — see
    :func:`sm_records.services.schema_change.apply`.

    ``0`` disables the reuse and prunes every job immediately, which is the
    setting for an install that would rather pay the second pass.
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

    def clamp_page_size(self, requested: int | None) -> int:
        """The page size a list endpoint actually uses.

        One owner for the rule, because four call sites want it and they must
        agree: the admin list, the referrers panel, the anonymous read API and
        the record-list view. ``None`` means "the caller did not ask" and gets
        :attr:`default_page_size`; anything above :attr:`max_page_size` is
        clamped rather than refused, so an anonymous caller probing the
        ceiling learns nothing and gets a usable page either way.
        """
        return max(min(requested or self.default_page_size, self.max_page_size), 1)

    @field_validator("public_route_prefix")
    @classmethod
    def _check_prefix(cls, value: str) -> str:
        """Refuse a prefix that would exempt the admin surface — or the whole
        host — from ``AuthMiddleware``. See :func:`check_public_route_prefix`."""
        return check_public_route_prefix(value)

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
