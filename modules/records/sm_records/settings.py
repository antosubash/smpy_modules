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
the first point at which the prefix is known, and long after the router table
would otherwise be built (see :mod:`sm_records.boot`).

``content_locales`` and ``default_content_locale`` carry it too, and those
three are the whole ``requires_restart`` set below — the README's settings
table lists the same three. Both locale values *are* read per request, so
screens follow an edit immediately; the flag is there because an edit changes
what the install *publishes* rather than how a page renders. Records already
written in a dropped locale stay written, the public API stops serving them,
and they are counted at startup and only there (:mod:`sm_records.health`).

Everything else here is read per request and takes effect on save.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from sm_records import constants
from sm_records.settings_checks import (
    DEFAULT_PUBLIC_ROUTE_PREFIX,
    check_content_locales,
    check_limits,
    check_public_route_prefix,
)

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

        The hydrator passes stored overrides as keyword arguments, so any
        field has exactly two answers: what the database says, or the default
        declared here. Dropping the env sources rather than merely not
        documenting them is deliberate — a stray ``SM_RECORDS_*`` in a shell
        or a deploy manifest would otherwise quietly outrank the value an
        operator can see and edit on the Settings screen.
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

    content_locales: tuple[str, ...] = Field(
        default=(constants.DEFAULT_CONTENT_LOCALE,), json_schema_extra=_RESTART
    )
    """Languages a record may be authored in (Phase 5 §4.2).

    Edited on the Settings screen as a JSON array — ``["en","de","fr"]``. A
    single entry (the default) is what a monolingual install runs on and costs
    it nothing: every record is in that locale, no type is translatable, and
    the public API behaves exactly as it did before there was such a thing as a
    language.

    **Deliberately this module's own setting and not pagebuilder's.**
    ``records`` must not depend on ``pagebuilder`` — it is published on its own
    and a host may install either without the other — and the two may
    legitimately publish in different language sets: a site can run a
    four-language marketing site off pagebuilder while its product catalogue is
    English-only. A host that wants them aligned sets both; the README says so.

    Distinct again from the host's ``SM_I18N_SUPPORTED_LOCALES``, which decides
    what language the *admin console* speaks rather than what the content is
    published in.
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

    default_page_size: int = 25
    """Page size for a list endpoint that receives no explicit ``limit``."""

    max_page_size: int = 200
    """Largest ``limit`` a caller may request. At least :attr:`default_page_size`."""

    revision_limit: int = Field(default=50, ge=1)
    """How many ``records_revision`` rows are kept per record.

    Append-only revisions are cheap insurance against a bad edit, but
    unbounded on a busy type they outgrow the document table itself — the
    oldest revisions beyond this count are pruned on write.

    At least 1: there is no "unlimited" setting, and ``0`` — which an operator
    would read as "keep no history" — is not representable rather than
    silently meaning the opposite. Every write appends one, so a limit of 1
    keeps exactly the current revision.
    """

    max_filter_terms: int = Field(default=20, ge=1)
    """Most ``?filter=`` terms one listing takes; over it is a ``400`` naming
    ``filter``. Each term is another correlated ``EXISTS`` over an index."""

    max_sort_terms: int = Field(default=5, ge=1)
    """Most *distinct* ``?sort=`` fields (repeats deduplicate first); each is
    another ``LEFT JOIN``, and a hundred was SQLite's join ceiling: a 500."""

    max_in_values: int = Field(default=200, ge=1)
    """Most values one ``filter=<field>:in:a,b`` term lists; two thousand
    was ``Expression tree is too large`` — to an anonymous caller."""

    max_payload_bytes: int = 262144
    """Reject a record write whose ``data`` payload, serialized, exceeds this
    many bytes (default 256 KB)."""

    max_import_bytes: int = 52428800
    """Reject an import whose uploaded body exceeds this many bytes (default
    50 MB), **before** it is parsed: ``Content-Length`` first, then byte by
    byte while reading, since a chunked request carries no length header and
    is exactly the body that must not be buffered whole to be refused. The
    ceiling is on the file; one oversized row is :attr:`max_payload_bytes`."""

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

    max_aggregate_groups: int = Field(default=1000, ge=1)
    """How many groups ``GET /types/{key}/records/aggregate`` returns before it
    stops (Phase 5 §5.1).

    A ``GROUP BY`` over an unbounded number of groups is as expensive as an
    unbounded ``COUNT`` and for the same reason — the database has to produce
    every group before it can order them — so the statement is bounded to
    ``max_aggregate_groups + 1`` rows and the response says ``truncated: true``
    when it hit the ceiling. Groups come back by count descending, so what is
    dropped is always the long tail, which is what a dashboard wants.

    It bounds the **stored** reading (``?reduce=``) identically: a maintained
    aggregate with a hundred thousand groups is a table as big as the type,
    and a caller asking for all of it should page a list instead.
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

    menu_refresh_seconds: int = Field(default=5, ge=0)
    """How stale a per-type admin sidebar entry may get, in seconds.

    A type with ``show_in_menu`` has its own sidebar item
    (:mod:`sm_records.menu`) and the framework's menu registry is filled once
    at boot, so a worker that did not serve the write re-reads the types at
    most this often, on a request that renders a sidebar. The worker that
    *did* serve it re-reads on its next one regardless — so this is the window
    another process can lag by, not a delay the editor sees. ``0`` re-reads on
    every page request. No restart: it is read at the moment of the check.
    """

    reindex_stale_after_seconds: int = 900
    """A ``reindex_pending`` entry (design doc §8.5) older than this degrades
    ``/health/ready`` and names the type and field (default 15 minutes).

    Turns an orphaned reindex — one whose background task died with the
    worker that owned it — from a support ticket into an alert.
    """

    def clamp_page_size(self, requested: int | None) -> int:
        """The page size a list endpoint actually uses.

        One owner for the rule, because four call sites must agree on it: the
        admin list, the referrers panel, the anonymous read API and the
        record-list view. ``None`` means "the caller did not ask" and gets
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
    def _check_locales(self) -> RecordsSettings:
        """The three rules :mod:`sm_records.locales` then takes for granted —
        see :func:`~sm_records.settings_checks.check_content_locales`."""
        check_content_locales(self.content_locales, self.default_content_locale)
        return self

    @model_validator(mode="after")
    def _check_limits(self) -> RecordsSettings:
        """The two cross-field ceilings — see
        :func:`~sm_records.settings_checks.check_limits`."""
        check_limits(self)
        return self
