"""core event_payloads helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordRestored,
    RecordTrashed,
    RecordTypeChanged,
    RecordTypeDeleted,
    RecordUpdated,
)
from sm_records.core.tenancy import bound_tenant
from sm_records.schema.diff import diff_fields
from sm_records.schema.fields import validate_fields
from sm_records.schema.types import ChangeClass


def _tenant(rtype: Any) -> str:
    """The tenant an event names: the type row's own. :func:`bound_tenant` is
    the fallback for a caller that hands over something without the column."""
    return getattr(rtype, "tenant_id", None) or bound_tenant()


def created(rtype: Any, record: Any) -> RecordCreated:
    return RecordCreated(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        uuid=record.uuid,
        locale=record.locale,
        translation_group=record.translation_group,
        status=record.status.value,
    )


def updated(rtype: Any, record: Any, *, status_before: str) -> RecordUpdated:
    """``status_before`` is read by the caller *before* the write, because the
    service mutates the instance in place — by the time this is called there
    is only one status left to read."""
    return RecordUpdated(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        uuid=record.uuid,
        version=record.version,
        status_before=status_before,
        status_after=record.status.value,
    )


def trashed(rtype: Any, record: Any, cascade: Iterable[tuple[Any, Any]]) -> list[RecordTrashed]:
    """One event per record the delete actually trashed.

    ``cascade`` is what ``soft_delete_record`` returns: every ``(record,
    type)`` pair it trashed, the one the caller named included. That record's
    event carries ``cascaded_from=None`` and every other one carries its uuid,
    which is the distinction design §9's ``cascade`` makes and that no
    subscriber could reconstruct — the cascaded records belong to types the
    request never mentioned.
    """
    return [
        RecordTrashed(
            type_key=doomed_type.key,
            tenant_id=_tenant(doomed_type),
            uuid=doomed.uuid,
            cascaded_from=None if doomed.uuid == record.uuid else record.uuid,
        )
        for doomed, doomed_type in cascade
    ]


def restored(rtype: Any, record: Any) -> RecordRestored:
    return RecordRestored(type_key=rtype.key, tenant_id=_tenant(rtype), uuid=record.uuid)


def purged(rtype: Any, record: Any) -> RecordPurged:
    return _purged(rtype.key, _tenant(rtype), record)


def _purged(type_key: str, tenant: str, record: Any) -> RecordPurged:
    return RecordPurged(
        type_key=type_key,
        tenant_id=tenant,
        uuid=record.uuid,
        locale=record.locale,
        translation_group=record.translation_group,
    )


def type_changed(rtype: Any, before: Sequence[dict[str, Any]]) -> RecordTypeChanged:
    """The event for one accepted write to a type row.

    ``before`` is the type's stored ``fields`` as they were *before* the call,
    which the endpoint reads off the row it loaded. The diff is recomputed
    here rather than threaded back out of the service, because the two
    services that write a type row — ``update_type`` and ``schema_change.apply``
    — do not return the same thing and neither returns it to every caller.
    It costs no query: ``diff_fields`` compares two field lists in memory, and
    an empty diff (a label edit, a pointer move) is the honest ``additive``.
    """
    old_defs = validate_fields([dict(raw) for raw in before])
    new_defs = validate_fields([dict(raw) for raw in (rtype.fields or [])])
    diff = diff_fields(old_defs, new_defs)
    return RecordTypeChanged(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        schema_version=rtype.schema_version,
        kind=diff.kind.value,
        index_affecting_keys=tuple(diff.keys(ChangeClass.INDEX_AFFECTING)),
    )


def type_deleted(type_key: str, records: Sequence[Any]) -> list[Any]:
    """``RecordTypeDeleted`` plus one ``RecordPurged`` per record that went
    with it — the records first, so a subscriber that drops its own rows per
    record and then forgets the type sees them in that order.

    The purge events carry what the rows held, because after this there is
    nothing to read them from. The table set a record lived in is not part of
    any event, since a subscriber addresses records by ``(type_key, uuid)``
    exactly as the API does.

    The tenant is the bound one. The type row is deleted by the time this is
    called, and the request that deleted it was bound to the row's tenant.
    """
    tenant = bound_tenant()
    events: list[Any] = [_purged(type_key, tenant, record) for record in records]
    events.append(RecordTypeDeleted(type_key=type_key, tenant_id=tenant, purged=len(records)))
    return events
