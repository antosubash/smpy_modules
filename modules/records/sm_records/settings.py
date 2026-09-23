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

``content_locales`` and ``default_content_locale`` carry it too. Both locale
values *are* read per request, so screens follow an edit immediately; the flag
is there because an edit changes what the install *publishes* rather than how
a page renders. Records written in a dropped locale stay written, the public
API stops serving them, and they are counted at startup and only there
(:mod:`sm_records.health`).

``media_api_prefix`` is the fourth: the media backend the ``media`` field
picker talks to is chosen once, from ``on_startup`` (:mod:`sm_records.media`).
Those four are the whole ``requires_restart`` set, and they are declared on
the base class :class:`~sm_records.settings_boot.BootSettings` — the README's
settings table lists the same four.

Everything else is read per request and takes effect on save. The cross-field
checks, and the page-size clamp, live in :mod:`sm_records.settings_checks`.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from sm_records.settings_boot import BootSettings
from sm_records.settings_checks import (
    DEFAULT_PUBLIC_ROUTE_PREFIX,
    check_limits,
    check_public_route_prefix,
    clamp_page_size,
)

__all__ = ["DEFAULT_PUBLIC_ROUTE_PREFIX", "RecordsSettings", "check_public_route_prefix"]


class RecordsSettings(BootSettings):
    # ``use_attribute_docstrings`` puts the prose under each field on the
    # Settings screen: the admin UI renders ``FieldInfo.description``, and
    # without this every field would arrive there unexplained while the
    # explanation sat in the source three lines below it.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    default_page_size: int = 25
    """Page size for a list endpoint that receives no explicit ``limit``."""

    max_page_size: int = 200
    """Largest ``limit`` a caller may request. At least :attr:`default_page_size`."""

    revision_limit: int = Field(default=50, ge=1)
    """How many ``records_revision`` rows are kept per record.

    Append-only revisions are cheap insurance against a bad edit, but unbounded
    on a busy type they outgrow the document table itself — the oldest beyond
    this count are pruned on write. At least 1: there is no "unlimited"
    setting, and ``0`` — which an operator would read as "keep no history" — is
    not representable rather than silently meaning the opposite. Every write
    appends one, so a limit of 1 keeps exactly the current revision.
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

    public_cache_seconds: int = Field(default=60, ge=0)
    """``max-age`` on an anonymous read, and whether it is cacheable at all.

    ``GET {public_route_prefix}/…`` is the one surface with no session behind
    it, so it is the one a CDN or a reverse proxy can hold — and it sent
    neither ``ETag`` nor ``Cache-Control``, so every anonymous reader was a
    full page build. ``updated_at``/``published_at`` are already on the row,
    which makes a weak validator nearly free; a conditional GET that matches is
    a ``304`` with no body.

    ``0`` sends ``no-store`` instead and skips the validator, for an install
    whose "published" means "visible the instant it is saved".

    Nothing on the admin API takes this: those responses are per-caller and
    ``InertiaCache`` already forces them private.
    """

    max_import_bytes: int = 52428800
    """Reject an import whose uploaded body exceeds this many bytes (default
    50 MB), **before** it is parsed: ``Content-Length`` first, then byte by
    byte while reading, since a chunked request carries no length header and
    is exactly the body that must not be buffered whole to be refused. The
    ceiling is on the file; one oversized row is :attr:`max_payload_bytes`."""

    max_import_rows: int = Field(default=20000, ge=1)
    """Reject an import holding more rows than this — a ``413``, before a row
    is written (default 20,000).

    :attr:`max_import_bytes` bounds the *file*; this bounds the *work*. That
    byte ceiling permits roughly 1.7 M rows, which is hours inside one HTTP
    request and long past any reverse proxy's read timeout — at which point
    the client sees a 504 while the server keeps writing.

    A JSON file is counted exactly, from the parsed document, before a row is
    validated. A CSV has no cheap exact count (a quoted cell may contain
    newlines), so its rows are counted as they are read and the parse stops at
    the first one past the ceiling: bounded work either way.
    """

    max_bulk_records: int = Field(default=500, ge=1)
    """Most records one ``POST …/records/bulk`` may name — a ``413`` over it,
    before a record is touched (default 500). The batch is one transaction and
    therefore one rollback (:mod:`sm_records.services.bulk`), so every record
    in it holds its locks until the request commits. It bounds the *named*
    records only: a ``trash`` that cascades reaches records it never counted,
    and ``POST …/records/trash/empty`` is outside it entirely, since the point
    of emptying the trash is not having to name what is in it."""

    max_fields_per_type: int = 100
    """Largest number of field definitions a single Record Type may declare."""

    max_indexed_fields_per_type: int = 25
    """Largest number of *indexed* field definitions a single Record Type may
    declare. Must not exceed :attr:`max_fields_per_type`.

    Easy to omit and expensive to add later: every indexed field is a row
    written per record per save, so a type with 80 indexed fields turns one save
    into 81 inserts. A visible ceiling makes that a design conversation at
    schema-editing time instead of an incident.
    """

    max_count: int = Field(default=10000, ge=1)
    """How far a list page's ``total`` is counted exactly before it is capped.

    A page can stop after ``page_size`` matches; the ``COUNT`` behind ``total``
    never can, so an unbounded one is O(matches) on a request whose page is
    O(25) — the cost of a filter matching most of a large type, paid on every
    page of it. The count is bounded to ``max_count + 1`` rows instead: at or
    below the ceiling ``total`` is exact and ``total_capped`` is ``false``,
    above it ``total`` is ``max_count`` and ``total_capped`` is ``true``, which
    the list screen renders as "10,000+". A caller paging with ``?after=`` that
    does not need the number should send ``?total=false`` and skip it entirely.
    """

    max_aggregate_groups: int = Field(default=1000, ge=1)
    """How many groups ``GET /types/{key}/records/aggregate`` returns before it
    stops (Phase 5 §5.1).

    A ``GROUP BY`` over an unbounded number of groups is as expensive as an
    unbounded ``COUNT`` and for the same reason — the database has to produce
    every group before it can order them — so the statement is bounded to
    ``max_aggregate_groups + 1`` rows and the response says ``truncated: true``
    when it hit the ceiling. Groups come back by count descending, so what is
    dropped is always the long tail, which is what a dashboard wants. It bounds
    the **stored** reading (``?reduce=``) identically: a maintained aggregate
    with a hundred thousand groups is a table as big as the type.
    """

    preview_sync_limit: int = Field(default=5000, ge=0)
    """Largest type ``POST /types/{key}/schema/preview`` will dry-run inside
    the request (design §8.9).

    A dry run validates every record of the type, trash included, at roughly a
    thousand records a second — fine for a small type and a multi-minute HTTP
    request for a large one, with whatever proxy timeout that implies. Above
    this many records the endpoint answers ``202`` with a job id and runs the
    scan through the module's deferred-job mechanism; the caller polls
    ``GET /types/{key}/schema/preview/{job}``. ``0`` sends every preview
    through the job, which is the setting to reach for behind a short timeout.
    """

    preview_job_ttl_seconds: int = Field(default=600, ge=0)
    """How long a finished preview job's report stays reusable.

    Two things read it: the job registry prunes anything older, and ``PUT
    /types/{key}`` reuses a completed job's report instead of re-running the
    scan inline when the job was taken against the same type, the same proposed
    fields and the same ``RecordType.version`` — see
    :func:`sm_records.services.schema_change.apply`. ``0`` disables the reuse
    and prunes every job immediately, for an install that would rather pay the
    second pass.
    """

    reindex_batch_size: int = 500
    """Number of records processed per batch by the reindex command and by a
    schema-triggered index-table migration (design doc §8.5)."""

    menu_refresh_seconds: int = Field(default=5, ge=0)
    """How stale a per-type admin sidebar entry may get, in seconds.

    A type with ``show_in_menu`` has its own sidebar item
    (:mod:`sm_records.menu`) and the framework's menu registry is filled once at
    boot, so a worker that did not serve the write re-reads the types at most
    this often, on a request that renders a sidebar. The worker that *did*
    serve it re-reads on its next one regardless — so this is the window another
    process can lag by, not a delay the editor sees. ``0`` re-reads every time.
    """

    reindex_stale_after_seconds: int = 900
    """A ``reindex_pending`` entry (design doc §8.5) older than this degrades
    ``/health/ready`` and names the type and field (default 15 minutes). Turns
    an orphaned reindex — one whose background task died with the worker that
    owned it — from a support ticket into an alert.
    """

    admin_header_tenant: bool = False
    """Multi-tenant hosts only: let a user holding ``admin`` who has **no tenant
    of their own** work in the tenant their ``X-Tenant-ID`` header names.

    Off, such a user gets a 403 ``tenant_required`` on every records screen,
    header or not: the framework lets any tenant-less user pick a tenant by
    header, and records refuses to follow it by default. Turn it on for an
    operator account that administers several tenants. Ignored on a
    single-tenant host, where everything is the ``default`` tenant.
    """

    def clamp_page_size(self, requested: int | None) -> int:
        """See :func:`~sm_records.settings_checks.clamp_page_size`."""
        return clamp_page_size(self, requested)

    @model_validator(mode="after")
    def _check_limits(self) -> RecordsSettings:
        """The two cross-field ceilings — see
        :func:`~sm_records.settings_checks.check_limits`."""
        check_limits(self)
        return self
