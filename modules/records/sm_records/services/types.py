"""Record Type CRUD — the schema half of the module.

A type's ``fields`` is a JSON column on one row, so changing it is an
``UPDATE`` and never DDL (design §4, §8.1). What that ``UPDATE`` is allowed to
be is the whole of §8, and Phase 3 ships it: a ``fields`` edit on a type that
already holds records is classified, dry-run and — if it would leave rows
invalid — refused with a report, by
:mod:`sm_records.services.schema_change`. ``update_type`` routes there rather
than re-implementing any of it; what stays here is the row lifecycle around
the schema (labels, flags, the delete) and the fast path for a type with no
records, where there is nothing to classify against and nothing to reindex.

Phase 1's blanket refusal — a type that held any record had read-only
``fields`` — is gone from this path, and so is the exception that expressed
it: nothing raises it, so keeping it importable would only leave an error the
endpoints layer maps and no code path can produce.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records._text import has_nul
from sm_records.constants import MAX_KEY_LEN, RESERVED_TYPE_KEYS, TYPE_KEY_PATTERN
from sm_records.models import RecordType, RecordTypeRevision
from sm_records.public_submissions import config as submissions
from sm_records.services._common import (
    PurgedRecord,
    record_count,
    record_counts,
    type_id_map,
)
from sm_records.services._lock import lock_type
from sm_records.services._referrer_sets import _declares_a_relation_to
from sm_records.services._schema import (
    check_pointers,
    check_targets,
    check_type_text,
    snapshot,
)
from sm_records.services._schema_checked import normalise_checked
from sm_records.services._type_checks import check_collection
from sm_records.services._type_update import update_type
from sm_records.services.errors import (
    Conflict,
    NotFound,
    ReferencedByOthers,
    ValidationFailed,
)
from sm_records.services.records import purge_type_records
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = [
    "create_type",
    "delete_type",
    "get_type",
    "get_type_by_id",
    "list_types",
    "record_count",
    "record_counts",
    "type_id_map",
    "update_type",
]

_KEY_RE = re.compile(TYPE_KEY_PATTERN)


async def list_types(db: AsyncSession) -> list[RecordType]:
    stmt = select(RecordType).order_by(RecordType.label, RecordType.key)
    return list((await db.execute(stmt)).scalars().all())


async def get_type(db: AsyncSession, key: str) -> RecordType:
    """One type by key, or the 404 every unknown key gets.

    A key carrying a NUL never reaches the statement. ``TYPE_KEY_PATTERN``
    means no stored key can contain one, so the honest answer is the same 404
    an unknown key gets — but asked, it was a bound ``varchar`` parameter and
    therefore the driver's ``CharacterNotInRepertoireError``, i.e. a 500 on
    ``/api/records/types/a%00b/records`` for any caller who can reach the
    admin API. :mod:`sm_records._text` has the rest of the reasoning.
    """
    if has_nul(key):
        raise NotFound(f"no record type with key {key!r}")
    rtype = (await db.execute(_owned_types().where(RecordType.key == key))).scalars().first()
    if rtype is None:
        raise NotFound(f"no record type with key {key!r}")
    return rtype


def _owned_types():
    """``select(RecordType)`` in the bound tenant, **said explicitly**.

    The framework's loader criteria already add the same predicate to a
    ``select(RecordType)``; a type key is where a caller's string becomes a
    row, so this lookup does not rest on them alone (tenancy design §E). Two
    tenants may both have ``post``, and with no tenant bound ``.first()``
    would pick either (FACT 1b) — here it is ``TenantUnbound`` instead.
    """
    return select(RecordType).where(RecordType.tenant_id == bound_tenant())


async def get_type_by_id(db: AsyncSession, type_id: int) -> RecordType:
    rtype = (await db.execute(_owned_types().where(RecordType.id == type_id))).scalars().first()
    if rtype is None:
        raise NotFound(f"no record type with id {type_id!r}")
    return rtype


async def create_type(
    db: AsyncSession,
    *,
    key: str,
    label: str,
    settings: RecordsSettings,
    label_plural: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    fields_raw: list[dict[str, Any]] | None = None,
    display_field: str | None = None,
    slug_field: str | None = None,
    is_public: bool = False,
    show_in_menu: bool = False,
    translatable: bool = False,
    allowed_roles: list[str] | None = None,
    collection: str | None = None,
    public_submissions: dict[str, Any] | None = None,
    actor: str | None = None,
) -> RecordType:
    if key in RESERVED_TYPE_KEYS:
        raise ValidationFailed(
            f"key {key!r} is reserved: it would shadow a records screen",
            [{"field": "key", "message": "reserved"}],
        )
    if not _KEY_RE.match(key or "") or len(key) > MAX_KEY_LEN:
        raise ValidationFailed(
            f"key must match {TYPE_KEY_PATTERN} and be at most {MAX_KEY_LEN} characters",
            [{"field": "key", "message": f"{key!r} is not a valid type key"}],
        )
    taken = select(RecordType.id).where(
        RecordType.key == key, RecordType.tenant_id == bound_tenant()
    )
    if (await db.execute(taken)).scalars().first():
        raise Conflict(f"a record type with key {key!r} already exists")

    check_collection(collection)
    check_type_text(
        {
            "label": label,
            "label_plural": label_plural,
            "description": description,
            "icon": icon,
            "allowed_roles": allowed_roles,
        }
    )
    config = submissions.parse(public_submissions)
    defs, fields = await normalise_checked(
        fields_raw or [], settings, kind=(config or {}).get("kind")
    )
    display_field = submissions.default_display(config, display_field)
    check_pointers(defs, display_field, slug_field)
    await check_targets(db, defs, key)

    rtype = RecordType(
        key=key,
        label=label,
        label_plural=label_plural or label,
        description=description,
        icon=icon,
        fields=fields,
        schema_version=1,
        version=1,
        display_field=display_field,
        slug_field=slug_field,
        is_public=is_public,
        show_in_menu=show_in_menu,
        translatable=translatable,
        allowed_roles=list(allowed_roles or []),
        collection=collection,
        public_submissions=submissions.settle(config, fields, is_public),
        created_by=actor,
    )
    try:
        # A savepoint, so losing the race leaves the request's transaction
        # usable. ``add`` goes *inside* it: ``begin_nested`` flushes whatever
        # is pending first, and a row flushed there is outside the savepoint.
        async with db.begin_nested():
            db.add(rtype)
            await db.flush()
    except IntegrityError as exc:
        # The SELECT above is only a check; the unique (tenant_id, key) index
        # is the authority, and a concurrent create that passed the same
        # check lands here. Same 409 as the sequential duplicate, but only for
        # *that* violation: an FK or NOT NULL failure must stay a 500. The
        # insert blocked on the winner's uncommitted row, so by now it is
        # committed and a fresh look at the key sees it.
        if (await db.execute(taken)).scalars().first():
            raise Conflict(f"a record type with key {key!r} already exists") from exc
        raise
    await snapshot(db, rtype, actor)
    return rtype


async def delete_type(
    db: AsyncSession, rtype: RecordType, *, confirm_record_count: int
) -> list[PurgedRecord]:
    """Delete a type and everything stored against it.

    ``confirm_record_count`` has to match what the type actually holds (§8.9):
    the count is what the operator was shown, and a mismatch means content
    arrived between the dialog and the click. Refusing is the only honest
    answer — the confirmation they gave was for a different amount of data.

    "Holds" counts the trash, because :func:`purge_type_records` purges it —
    a type with nothing live and fifty restorable records used to be deletable
    on a confirmation of ``0``, which destroyed all fifty. ``TypeRead`` carries
    ``trashed_record_count`` alongside ``record_count`` so the dialog can show
    the operator the number this check will actually compare against.

    Returns one :class:`~sm_records.services._common.PurgedRecord` per record
    it purged, and emits a ``RecordPurged`` for each — the one event whose
    subject no subscriber can read back — then ``RecordTypeDeleted``.
    Identity only (``uuid``, ``locale``, ``translation_group``), because the
    purge itself is set-based and never instantiates the rows: see
    :func:`purge_type_records`.
    """
    # Before the count: a move committing under it would leave this purging
    # the tables the type just left (``services._lock.lock_types``).
    await lock_type(db, rtype)
    held = await record_count(db, rtype, include_deleted=True)
    if confirm_record_count != held:
        raise Conflict(
            f"type {rtype.key!r} holds {held} record(s), not {confirm_record_count}; "
            "reload and confirm again"
        )
    referring = [
        other.key
        for other in await list_types(db)
        if other.id != rtype.id and _declares_a_relation_to(other.fields, rtype.key)
    ]
    if referring:
        raise ReferencedByOthers(
            f"type {rtype.key!r} is the target of a relation on {referring}", referring
        )
    key = rtype.key
    purged = await purge_type_records(db, rtype)
    # Explicit, not via the FK's ON DELETE CASCADE: SQLite leaves foreign keys
    # unenforced unless the pragma is on, so the cascade would clean up on
    # Postgres and orphan rows on the default dev backend.
    # Core DML: no tenant filter reaches it but this predicate (tenancy §E).
    await db.execute(
        sa_delete(RecordTypeRevision).where(
            RecordTypeRevision.type_id == rtype.id,
            RecordTypeRevision.tenant_id == bound_tenant(),
        )
    )
    await db.delete(rtype)
    await db.flush()
    events.emit(db, *events.type_deleted(key, purged))
    return purged
