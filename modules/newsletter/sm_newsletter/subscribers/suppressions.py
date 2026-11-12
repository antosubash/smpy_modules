"""The suppression listing and the lookup by address (PR 6, Task 7).

A row is shown only when it is address-wide (``list_type_key == ""``) or its
list is one the caller may read (records' narrowing, through
:func:`~sm_newsletter.campaigns.access.readable_lists`); the per-reason counts
use the same visibility. Rows carry the hash, never an address: the console
shows a fingerprint, and the lookup hashes what the admin typed.

Decision (ruling TL1): the subscriber browse and detail keep a tenant-wide
``suppressed`` flag that is *not* narrowed by this visibility. Suppressions are
tenant-wide by design, so the flag means "this address will receive no
newsletter mail", and an admin of a readable list needs to know that. The
accepted disclosure is that single boolean; for a list the caller cannot read,
the kind (reason), source, list, ``created_at``, version and fingerprint of the
rows stay hidden, and every row-shaped answer goes through :func:`visible`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles, readable_lists
from sm_newsletter.core.constants import LIFTABLE, REASON_UNSUBSCRIBED, REASONS
from sm_newsletter.core.errors_audience import InvalidQuery
from sm_newsletter.core.suppression import lookup_hashes
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression

__all__ = [
    "FINGERPRINT_LEN",
    "SuppressionRow",
    "as_row",
    "lift_block",
    "list_suppressions",
    "rows_for_email",
    "visible",
    "visible_lists",
]

FINGERPRINT_LEN = 12
_T = Suppression.__table__


@dataclass(frozen=True)
class SuppressionRow:
    id: int
    email_hash: str
    reason: str
    list_type_key: str
    source: str
    created_at: datetime

    @property
    def version(self) -> str:
        """The opaque row version the console echoes back (C3): a refresh moves it."""
        return self.created_at.isoformat()


def as_row(raw) -> SuppressionRow:
    return SuppressionRow(
        id=raw.id,
        email_hash=raw.email_hash,
        reason=raw.reason,
        list_type_key=raw.list_type_key,
        source=raw.source,
        created_at=raw.created_at,
    )


async def visible_lists(session: AsyncSession, *, tenant_id: str, roles: Roles) -> list[str]:
    """The tenant's lists whose opt-outs this caller may see."""
    return await readable_lists(session, tenant_id=tenant_id, roles=roles)


def visible(keys: list[str], column=None):
    """The ``WHERE`` that keeps address-wide rows and those of ``keys``
    (on ``column``, the suppression table's by default)."""
    col = _T.c.list_type_key if column is None else column
    return or_(col == "", col.in_(keys))


async def list_suppressions(
    session: AsyncSession,
    *,
    tenant_id: str,
    roles: Roles,
    reason: str | None,
    offset: int,
    limit: int,
) -> tuple[list[SuppressionRow], int, dict[str, int]]:
    """Visible rows, newest first, paged; the total under ``reason``; and the
    count per reason over every visible row."""
    if reason is not None and reason not in REASONS:
        raise InvalidQuery("reason: unknown")
    with tenant_scope(tenant_id):
        keys = await visible_lists(session, tenant_id=tenant_id, roles=roles)
        where = [_T.c.tenant_id == tenant_id, visible(keys)]
        filtered = [*where, *([_T.c.reason == reason] if reason else [])]
        stmt = (
            select(_T)
            .where(*filtered)
            .order_by(_T.c.created_at.desc(), _T.c.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [as_row(r) for r in (await session.execute(stmt)).all()]
        total = (
            await session.execute(select(func.count()).select_from(_T).where(*filtered))
        ).scalar_one()
        grouped = select(_T.c.reason, func.count()).where(*where).group_by(_T.c.reason)
        counts = dict.fromkeys(REASONS, 0)
        for key, n in (await session.execute(grouped)).all():
            if key in counts:
                counts[key] = int(n)
    return items, int(total), counts


async def rows_for_email(
    session: AsyncSession, *, tenant_id: str, roles: Roles, email: str
) -> list[SuppressionRow]:
    """The visible rows of one address (any spelling), newest first; ``[]``
    for an address that is not one."""
    try:
        digests = list(lookup_hashes(email))  # legacy-keyed rows too
    except ValueError:
        return []
    with tenant_scope(tenant_id):
        keys = await visible_lists(session, tenant_id=tenant_id, roles=roles)
        stmt = (
            select(_T)
            .where(_T.c.tenant_id == tenant_id, _T.c.email_hash.in_(digests), visible(keys))
            .order_by(_T.c.created_at.desc(), _T.c.id.desc())
        )
        return [as_row(r) for r in (await session.execute(stmt)).all()]


def lift_block(row: SuppressionRow, *, confirmed_at: datetime | None) -> str | None:
    """Why ``row`` cannot be lifted, or ``None``.

    ``lift_not_allowed`` for a reason outside ``LIFTABLE`` (a complaint);
    ``opt_out_stands`` for an opt-out unless ``confirmed_at`` is later than the
    row. The lift passes the locked ``ConfirmProof``'s time; a display passes a
    read-only one."""
    if row.reason not in LIFTABLE:
        return "lift_not_allowed"
    if row.reason == REASON_UNSUBSCRIBED and (
        confirmed_at is None or confirmed_at <= row.created_at
    ):
        return "opt_out_stands"
    return None
