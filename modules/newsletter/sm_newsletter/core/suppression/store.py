"""Reads and writes of ``newsletter_suppression``; the rules are in the package docstring.

Every function validates ``tenant_id``, binds it with
:func:`~sm_newsletter.core.tenancy.tenant_scope` and pins it in every
``WHERE`` and every inserted row (a Core ``INSERT`` is not stamped by the
tenant mixin). None commits: callers finish with
``simple_module_db.finalize_session``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import clock
from sm_newsletter.core.constants import (
    MAX_TYPE_KEY_LEN,
    REASON_HARD_BOUNCE,
    REASON_IMPORTED_CLEANED,
    REASON_UNSUBSCRIBED,
    REASONS,
    SOURCES,
)
from sm_newsletter.core.suppression.hashing import email_hash, normalise_email
from sm_newsletter.core.tenancy import tenant_scope, valid_tenant
from sm_newsletter.core.upsert import affected_rows, insert_ignore, upsert_newest
from sm_newsletter.models import Suppression

__all__ = ["clear_for_confirmation", "suppress", "suppress_many", "suppressed"]

_T = Suppression.__table__
_CONFLICT = ("tenant_id", "email_hash", "reason", "list_type_key")
_ADDRESS_WIDE_CLEARED = (REASON_HARD_BOUNCE, REASON_IMPORTED_CLEANED)
_IN_CHUNK = 500


def _tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not valid_tenant(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


def _list_key(list_type_key: object) -> str:
    if not isinstance(list_type_key, str) or not list_type_key:
        raise ValueError(f"not a list type key: {list_type_key!r}")
    if len(list_type_key) > MAX_TYPE_KEY_LEN:
        raise ValueError(f"list type key longer than {MAX_TYPE_KEY_LEN}: {list_type_key!r}")
    return list_type_key


def _check_row(reason: str, source: str, list_type_key: str) -> None:
    if reason not in REASONS:
        raise ValueError(f"unknown suppression reason: {reason!r}")
    if source not in SOURCES:
        raise ValueError(f"unknown suppression source: {source!r}")
    if reason == REASON_UNSUBSCRIBED:
        _list_key(list_type_key)
    elif list_type_key != "":
        raise ValueError(f"a {reason!r} row is address-wide; list_type_key must be ''")


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be an aware datetime, not {value!r}")
    return value


def _hashes(emails: Sequence[str]) -> dict[str, str]:
    """Normalised address -> hash, deduplicated; ``ValueError`` on a bad address."""
    if isinstance(emails, str):
        raise ValueError("emails must be a sequence of addresses, not one string")
    return {normalise_email(e): email_hash(e) for e in emails}


async def suppress_many(
    session: AsyncSession,
    *,
    tenant_id: str,
    emails: Sequence[str],
    reason: str,
    source: str,
    list_type_key: str = "",
    refresh: bool = True,
    keep_source: bool = False,
    now: datetime | None = None,
) -> int:
    """Suppress every address in ``emails``; returns how many rows were *inserted*.

    With ``refresh`` (the default) a row that already exists gets
    ``created_at = now`` and the new ``source``, so a repeated opt-out or
    bounce is newer than an earlier confirmation; a row already as new as
    ``now`` is left alone. One upsert per chunk (on SQLite preceded by a DO
    NOTHING insert in the same write transaction;
    :func:`~sm_newsletter.core.upsert.upsert_newest`): a row a confirmation
    deletes concurrently is inserted again, never lost. Requires a
    transactional (non-AUTOCOMMIT) SQLite connection, as the framework's
    engine is. ``refresh=False`` is a
    pure insert-ignore (the reconcile's, so its count is idempotent and it
    never freshens a row). ``keep_source=True`` refreshes ``created_at`` only:
    an existing row keeps its first writer's ``source`` (the records mirror's,
    so a page opt-out stays ``unsubscribe_page``); a new row still gets
    ``source``.
    """
    tenant = _tenant(tenant_id)
    _check_row(reason, source, list_type_key)
    at = clock.utcnow() if now is None else _aware(now, "now")
    hashes = sorted(set(_hashes(emails).values()))
    if not hashes:
        return 0
    rows = [
        {
            "tenant_id": tenant,
            "email_hash": h,
            "reason": reason,
            "list_type_key": list_type_key,
            "source": source,
            "created_at": at,
        }
        for h in hashes
    ]
    with tenant_scope(tenant):
        if not refresh:
            return await insert_ignore(session, _T, rows, conflict=_CONFLICT)
        return await upsert_newest(
            session,
            _T,
            rows,
            conflict=_CONFLICT,
            time_column="created_at",
            follow=() if keep_source else ("source",),
        )


async def suppress(
    session: AsyncSession,
    *,
    tenant_id: str,
    email: str,
    reason: str,
    source: str,
    list_type_key: str = "",
    refresh: bool = True,
    keep_source: bool = False,
    now: datetime | None = None,
) -> bool:
    """Suppress one address; ``True`` if this call inserted its row."""
    count = await suppress_many(
        session,
        tenant_id=tenant_id,
        emails=[email],
        reason=reason,
        source=source,
        list_type_key=list_type_key,
        refresh=refresh,
        keep_source=keep_source,
        now=now,
    )
    return count == 1


async def clear_for_confirmation(
    session: AsyncSession,
    *,
    tenant_id: str,
    email: str,
    list_type_key: str,
    confirmed_at: datetime,
) -> int:
    """Delete what a confirmation on ``list_type_key`` at ``confirmed_at`` lifts.

    That list's ``unsubscribed`` row and the address-wide ``hard_bounce`` /
    ``imported_cleaned`` rows, each only if ``created_at <= confirmed_at``.
    Never a complaint, never another list's opt-out. Returns rows deleted.
    """
    tenant = _tenant(tenant_id)
    key = _list_key(list_type_key)
    cutoff = _aware(confirmed_at, "confirmed_at")
    digest = email_hash(email)
    stmt = (
        delete(_T)
        .where(
            _T.c.tenant_id == tenant,
            _T.c.email_hash == digest,
            _T.c.created_at <= cutoff,
            or_(
                and_(_T.c.reason == REASON_UNSUBSCRIBED, _T.c.list_type_key == key),
                and_(_T.c.reason.in_(_ADDRESS_WIDE_CLEARED), _T.c.list_type_key == ""),
            ),
        )
        .execution_options(synchronize_session=False)
    )
    with tenant_scope(tenant):
        result = await session.execute(stmt)
    return affected_rows(result, session.get_bind().dialect.name)


async def suppressed(session: AsyncSession, *, tenant_id: str, emails: Sequence[str]) -> set[str]:
    """The normalised addresses among ``emails`` with any row in the tenant."""
    tenant = _tenant(tenant_id)
    by_hash = {h: addr for addr, h in _hashes(emails).items()}
    if not by_hash:
        return set()
    hashes = sorted(by_hash)
    found: set[str] = set()
    with tenant_scope(tenant):
        for start in range(0, len(hashes), _IN_CHUNK):
            stmt = (
                select(_T.c.email_hash)
                .where(
                    _T.c.tenant_id == tenant,
                    _T.c.email_hash.in_(hashes[start : start + _IN_CHUNK]),
                )
                .distinct()
            )
            found.update(by_hash[h] for h in (await session.execute(stmt)).scalars())
    return found
