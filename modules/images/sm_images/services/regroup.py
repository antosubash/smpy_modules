"""Group a collection's images by a filename pattern: the pieces both paths share.

Ported from the portal's ``regroup.py`` (bags, directions). The pattern is the
import pattern (:mod:`sm_images.imports.filename_pattern`): a ``regex`` with a
per-match timeout and length caps, so a hostile pattern costs a timeout count,
never the worker. Roles come from the collection's ``group_roles``.

A **small** collection regroups inside the request (:func:`regroup_now`, with
a preview that writes nothing); a big one runs as a resumable background job
(:mod:`sm_images.regroup`), which calls the same chunk primitives:

1. :func:`derive_chunk` - a pure plan for one chunk of images;
2. :func:`ensure_groups` - resolve every key to a group, creating the missing
   ones (``ON CONFLICT DO NOTHING``, so a competing insert is told apart);
3. :func:`apply_chunk` - one ``UPDATE ... CASE`` per chunk, counted by the
   rows it actually changed.

Idempotent: an image already exactly as derived is not rewritten. An image that
already has a group is left alone unless ``reassign``; a derivation with no role
keeps the role.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select

from sm_images import constants
from sm_images.errors import InvalidGroup
from sm_images.imports import filename_pattern as fp
from sm_images.models import Collection, Group, Image
from sm_images.services.regroup_write import Change, settle

__all__ = [
    "ChunkPlan",
    "RegroupResult",
    "Tally",
    "compile_or_422",
    "count_images",
    "derive_chunk",
    "fetch_chunk",
    "regroup_now",
]

TOO_SLOW = "The pattern took too long over this collection; nothing was changed"


@dataclass
class Tally:
    scanned: int = 0
    matched: int = 0
    no_match: int = 0
    timed_out: int = 0
    already_grouped: int = 0
    unchanged: int = 0
    assigned: int = 0
    groups_created: int = 0
    groups_existing: int = 0


@dataclass
class ChunkPlan:
    tally: Tally = field(default_factory=Tally)
    changes: list[Change] = field(default_factory=list)


@dataclass(frozen=True)
class RegroupResult:
    dry_run: bool
    tally: Tally


def compile_or_422(pattern: str) -> Any:
    try:
        return fp.compile_pattern(pattern)
    except fp.PatternError as exc:
        raise InvalidGroup(str(exc), constants.CODE_INVALID_PATTERN) from None


def _after(cursor: tuple[datetime, uuid.UUID] | None) -> Any:
    if cursor is None:
        return None
    at, last = cursor
    return or_(Image.created_at > at, and_(Image.created_at == at, Image.id > last))


async def fetch_chunk(
    db: Any,
    tenant: str,
    collection_id: uuid.UUID,
    cursor: tuple[datetime, uuid.UUID] | None,
    size: int,
) -> list[Any]:
    """The next ``size`` images by ``(created_at, id)`` after ``cursor``:
    ``(id, created_at, filename, group_id, group_role, group_key)`` rows."""
    stmt = (
        select(
            Image.id,
            Image.created_at,
            Image.filename,
            Image.group_id,
            Image.group_role,
            Group.key,
        )
        .outerjoin(Group, Group.id == Image.group_id)
        .where(Image.collection_id == collection_id, Image.tenant_id == tenant)
        .order_by(Image.created_at, Image.id)
        .limit(size)
    )
    after = _after(cursor)
    if after is not None:
        stmt = stmt.where(after)
    return list((await db.execute(stmt)).all())


def _derive(
    compiled: Any,
    roles: Sequence[str],
    rows: Sequence[Any],
    reassign: bool,
    deadline: float | None,
) -> ChunkPlan:
    plan = ChunkPlan()
    tally = plan.tally
    for image_id, _, filename, group_id, role_now, key_now in rows:
        remaining = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InvalidGroup(TOO_SLOW, constants.CODE_REGROUP_TOO_SLOW)
        tally.scanned += 1
        outcome, key, role = fp.derive(compiled, filename, roles, budget=remaining)
        if outcome == fp.TIMED_OUT:
            tally.timed_out += 1
        elif key is None:
            tally.no_match += 1
        else:
            tally.matched += 1
            if key_now == key and (role is None or role == role_now):
                tally.unchanged += 1
            elif group_id is not None and not reassign:
                tally.already_grouped += 1
            else:
                plan.changes.append((image_id, key, role))
    return plan


async def derive_chunk(
    compiled: Any,
    roles: Sequence[str],
    rows: Sequence[Any],
    reassign: bool,
    deadline: float | None = None,
) -> ChunkPlan:
    """Plan one chunk off the event loop. ``deadline`` (a ``time.monotonic``
    value) is checked before every match and caps each match's own timeout."""
    return await asyncio.to_thread(_derive, compiled, roles, rows, reassign, deadline)


async def count_images(db: Any, collection_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(Image).where(Image.collection_id == collection_id)
    return int((await db.execute(stmt)).scalar_one())


def _add(total: Tally, part: Tally) -> None:
    for name in vars(total):
        setattr(total, name, getattr(total, name) + getattr(part, name))


async def regroup_now(
    db: Any, tenant: str, collection: Collection, pattern: str, *, reassign: bool, dry_run: bool
) -> RegroupResult:
    """The whole regroup inside the caller's transaction (small collections)."""
    compiled = compile_or_422(pattern)
    roles = list(collection.group_roles or [])
    deadline = time.monotonic() + constants.REGROUP_BUDGET_SECONDS
    began = datetime.now(UTC)
    total = Tally()
    changes: list[Change] = []
    cursor = None
    while rows := await fetch_chunk(db, tenant, collection.id, cursor, constants.REGROUP_CHUNK):
        cursor = (rows[-1][1], rows[-1][0])
        plan = await derive_chunk(compiled, roles, rows, reassign, deadline)
        _add(total, plan.tally)
        changes += plan.changes
    assigned, created, existing = await settle(
        db, tenant, collection.id, changes, reassign=reassign, dry_run=dry_run, since=began
    )
    total.assigned, total.groups_created, total.groups_existing = assigned, created, existing
    return RegroupResult(dry_run, total)
