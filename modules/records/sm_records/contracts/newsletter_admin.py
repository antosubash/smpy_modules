"""The newsletter admin screens' reads of a records list (newsletter PR 6).

Beside :mod:`sm_records.contracts.newsletter`, which serves the sender: these
serve the console. Same rules — the caller names the tenant, it is validated,
bound with ``tenant_scope`` (naming another one while a tenant is bound raises
``TenantIsolationError``) and pinned as a ``WHERE`` in every query. A tenant
with no such list reads as empty. Argument errors are ``ValueError`` before any
query; a term records cannot answer raises :class:`SubscriberFilterError`.

Browsing lists subscribers in **any** status; it is not an audience.

:func:`lock_confirmation` is the one write-side call here: it locks the
subscriber's row for newsletter's suppression lift (C2).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.contracts._newsletter_args import SubscriberHit, _checked_tenant, _hit
from sm_records.core.constants import VIEW_PREFIX
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import campaign_browse, campaign_reads, subscribe
from sm_records.public_submissions.campaign_reads import SubscriberFilterError, moment
from sm_records.public_submissions.row_lock import lock_record
from sm_records.schema.types import FieldType

__all__ = [
    "BROWSE_STATUSES",
    "MAX_BROWSE_LIMIT",
    "MAX_BROWSE_OFFSET",
    "MAX_SEARCH_LEN",
    "BrowseStatus",
    "ConfirmProof",
    "FieldChoice",
    "ListField",
    "SubscriberFilterError",
    "SubscriberHit",
    "SubscriberPage",
    "browse_subscribers",
    "list_fields",
    "lock_confirmation",
    "subscriber_admin_url",
    "subscriber_status_counts",
]

BrowseStatus = Literal["pending", "confirmed", "unsubscribed"]
BROWSE_STATUSES: tuple[str, ...] = ("pending", "confirmed", "unsubscribed")
MAX_BROWSE_LIMIT = 100
MAX_BROWSE_OFFSET = 100_000
MAX_SEARCH_LEN = 200


class FieldChoice(SQLModel):
    value: str
    label: str


class ListField(SQLModel):
    key: str
    label: str
    type: str
    many: bool
    choices: list[FieldChoice]
    system: bool


class ConfirmProof(SQLModel):
    """A live subscriber's confirmation, read under its row lock."""

    uuid: str
    confirmed_at: datetime


class SubscriberPage(SQLModel):
    items: list[SubscriberHit]
    total: int


def _int(value: object, name: str, low: int, high: int) -> int:
    # `bool` is an `int`; `True` is a caller bug, not "one".
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f"{name} must be an int between {low} and {high}")
    return value


def _checked_browse_status(status: object) -> str | None:
    if status is not None and status not in BROWSE_STATUSES:
        raise ValueError(f"status must be one of {BROWSE_STATUSES}")
    return status  # type: ignore[return-value]


def _checked_search(search: object) -> str | None:
    if search is None:
        return None
    if not isinstance(search, str):
        raise ValueError("search must be a str")
    if len(search) > MAX_SEARCH_LEN or "\x00" in search:
        raise ValueError(f"search must be at most {MAX_SEARCH_LEN} characters, without NUL")
    return search.strip().lower() or None


def _field(raw: dict) -> ListField:
    ftype = str(raw.get("type") or "")
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    choices = [
        FieldChoice(value=str(c["value"]), label=str(c.get("label", c["value"])))
        for c in (options.get("choices") or [])
        if isinstance(c, dict) and "value" in c
    ]
    key = str(raw.get("key") or "")
    return ListField(
        key=key,
        label=str(raw.get("label") or key),
        type=ftype,
        many=ftype == FieldType.MULTISELECT.value,
        choices=choices if ftype in (FieldType.SELECT.value, FieldType.MULTISELECT.value) else [],
        system=bool(raw.get("system")),
    )


async def list_fields(session: AsyncSession, *, tenant_id: str, type_key: str) -> list[ListField]:
    """The list's fields a segment can filter on: indexed, not internal, not a
    relation, in declared order. ``[]`` for a tenant without that list;
    ``SubscriberFilterError("not_a_list")`` for a type that is not one."""
    tenant = _checked_tenant(tenant_id)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return []
        return [_field(f) for f in campaign_browse.declared_fields(rtype)]


async def browse_subscribers(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    status: BrowseStatus | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> SubscriberPage:
    """Untrashed subscribers in any status (or ``status``), newest first, with
    offset paging and an exact total. ``search`` is a case-insensitive literal
    substring of the address."""
    tenant = _checked_tenant(tenant_id)
    limit = _int(limit, "limit", 1, MAX_BROWSE_LIMIT)
    offset = _int(offset, "offset", 0, MAX_BROWSE_OFFSET)
    status, search = _checked_browse_status(status), _checked_search(search)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return SubscriberPage(items=[], total=0)
        rows, total = await campaign_browse.browse(
            session,
            rtype,
            tenant,
            filters=filters,
            status=status,
            search=search,
            offset=offset,
            limit=limit,
        )
        return SubscriberPage(items=[_hit(rtype, r) for r in rows], total=total)


async def subscriber_status_counts(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    filters: Sequence[str] = (),
    search: str | None = None,
) -> dict[str, int]:
    """Untrashed subscribers per status over the same filters and search;
    zeros for a tenant without that list."""
    tenant = _checked_tenant(tenant_id)
    search = _checked_search(search)
    with tenant_scope(tenant):
        rtype = await campaign_reads.list_type(session, tenant, type_key)
        if rtype is None:
            return dict.fromkeys(BROWSE_STATUSES, 0)
        return await campaign_browse.status_counts(
            session, rtype, tenant, filters=filters, search=search
        )


def subscriber_admin_url(type_key: str, uuid: str | None = None) -> str:
    """The records console URL of a list, or of one subscriber. Pure."""
    base = f"{VIEW_PREFIX}/{quote(type_key, safe='')}"
    return base if uuid is None else f"{base}/{quote(uuid, safe='')}"


async def lock_confirmation(
    session: AsyncSession, *, tenant_id: str, type_key: str, email: str
) -> ConfirmProof | None:
    """The untrashed subscriber of ``type_key`` holding ``email`` (normalised),
    locked to the end of the caller's transaction; a proof only when it is
    ``confirmed`` with a readable ``sm_confirmed_at``.

    ``None`` for an unknown, pending, unsubscribed or trashed one, a tenant
    without that list, or a type that is no longer a list. Must run inside the
    caller's write transaction: every unsubscribe takes the same lock before it
    decides, so the answer holds until the caller commits or rolls back."""
    tenant = _checked_tenant(tenant_id)
    if not isinstance(email, str) or not isinstance(type_key, str):
        raise ValueError("type_key and email must be str")
    address = subscribe.normalise(email)
    if not address:
        return None
    with tenant_scope(tenant):
        try:
            rtype = await campaign_reads.list_type(session, tenant, type_key)
        except SubscriberFilterError:
            return None
        found = None if rtype is None else await subscribe.find(session, rtype, address)
        if rtype is None or found is None:
            return None
        try:
            record = await lock_record(session, rtype, found)
        except NoResultFound:  # purged between the find and the lock
            return None
    data = record.data or {}
    confirmed_at = moment(data.get("sm_confirmed_at"))
    if (
        record.is_deleted
        or record.tenant_id != tenant
        or subscribe.normalise(data.get("sm_email")) != address
        or data.get("sm_status") != subscribe.CONFIRMED
        or confirmed_at is None
    ):
        return None
    return ConfirmProof(uuid=record.uuid, confirmed_at=confirmed_at)
