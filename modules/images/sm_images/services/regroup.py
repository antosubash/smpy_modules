"""Group a collection's images by a filename pattern.

Ported from the portal's ``regroup.py`` (bags, directions). The pattern is the
import pattern (:mod:`sm_images.imports.filename_pattern`): a ``regex`` with a
per-match timeout and length caps, so a hostile pattern costs a timeout count,
never the worker. Roles come from the collection's ``group_roles``.

Three phases, in one transaction:

1. **Plan** - read ``(id, filename, group, role)`` in id-keyed chunks and derive
   a target for each image. Pure; ``dry_run`` stops here. The plan has a time
   budget: a pattern too slow over this collection is refused with nothing
   written.
2. **Resolve** every key to a group (creating the missing ones) *before* any
   image is touched, so a lost creation race cannot drop assignments.
3. **Apply** one ``UPDATE ... CASE`` per chunk of images.

Idempotent: an image already exactly as derived is not rewritten, so a second
run reports ``unchanged`` and writes nothing. An image that already has a group
is left alone unless ``reassign``; a derivation with no role keeps the role.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, select, update

from sm_images import constants
from sm_images.errors import InvalidGroup
from sm_images.imports import filename_pattern as fp
from sm_images.models import Collection, Group, Image
from sm_images.schemas.group import RegroupOut

__all__ = ["regroup"]

_TOO_SLOW = "The pattern took too long over this collection; nothing was changed"


@dataclass
class _Plan:
    scanned: int = 0
    matched: int = 0
    no_match: int = 0
    timed_out: int = 0
    already_grouped: int = 0
    unchanged: int = 0
    changes: list[tuple[uuid.UUID, str, str | None]] = field(default_factory=list)
    """``(image_id, group_key, role-or-None-to-keep)``."""


def _derive_chunk(
    compiled: Any, roles: Sequence[str], rows: Sequence[Any], reassign: bool, plan: _Plan
) -> None:
    for image_id, filename, group_key_now, group_role_now, current_key in rows:
        plan.scanned += 1
        outcome, key, role = fp.derive(compiled, filename, roles)
        if outcome == fp.TIMED_OUT:
            plan.timed_out += 1
        elif key is None:
            plan.no_match += 1
        else:
            plan.matched += 1
            if current_key == key and (role is None or role == group_role_now):
                plan.unchanged += 1
            elif group_key_now is not None and not reassign:
                plan.already_grouped += 1
            else:
                plan.changes.append((image_id, key, role))


async def _plan(db: Any, collection: Collection, compiled: Any, reassign: bool) -> _Plan:
    roles = list(collection.group_roles or [])
    plan = _Plan()
    deadline = time.monotonic() + constants.REGROUP_BUDGET_SECONDS
    last: uuid.UUID | None = None
    while True:
        stmt = (
            select(Image.id, Image.filename, Image.group_id, Image.group_role, Group.key)
            .outerjoin(Group, Group.id == Image.group_id)
            .where(Image.collection_id == collection.id)
            .order_by(Image.id)
            .limit(constants.REGROUP_CHUNK)
        )
        if last is not None:
            stmt = stmt.where(Image.id > last)
        rows = (await db.execute(stmt)).all()
        if not rows:
            return plan
        last = rows[-1][0]
        shaped = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
        await asyncio.to_thread(_derive_chunk, compiled, roles, shaped, reassign, plan)
        if time.monotonic() > deadline:
            raise InvalidGroup(_TOO_SLOW, constants.CODE_REGROUP_TOO_SLOW)


async def _resolve(
    db: Any, collection: Collection, keys: Sequence[str]
) -> tuple[dict[str, uuid.UUID], int]:
    from sm_images.ingest.dedupe import ensure_group

    found: dict[str, uuid.UUID] = {}
    for i in range(0, len(keys), constants.REGROUP_CHUNK):
        batch = keys[i : i + constants.REGROUP_CHUNK]
        stmt = select(Group.key, Group.id).where(
            Group.collection_id == collection.id, Group.key.in_(batch)
        )
        found.update(dict((await db.execute(stmt)).all()))
    existing = len(found)
    for key in keys:
        if key not in found:
            found[key] = await ensure_group(db, collection.id, key)
    return found, len(found) - existing


async def _apply(
    db: Any,
    collection: Collection,
    changes: Sequence[tuple[uuid.UUID, str, str | None]],
    groups: dict[str, uuid.UUID],
    reassign: bool,
) -> None:
    for i in range(0, len(changes), constants.REGROUP_CHUNK):
        chunk = changes[i : i + constants.REGROUP_CHUNK]
        ids = [c[0] for c in chunk]
        group_case = case({c[0]: groups[c[1]] for c in chunk}, value=Image.id)
        roles = {c[0]: c[2] for c in chunk if c[2] is not None}
        role_case = (
            case(roles, value=Image.id, else_=Image.group_role) if roles else Image.group_role
        )
        stmt = update(Image).where(Image.id.in_(ids), Image.collection_id == collection.id)
        if not reassign:
            stmt = stmt.where(Image.group_id.is_(None))  # lost a race to a manual assignment
        await db.execute(
            stmt.values(group_id=group_case, group_role=role_case).execution_options(
                synchronize_session=False
            )
        )


async def regroup(
    db: Any, collection: Collection, pattern: str, *, reassign: bool, dry_run: bool
) -> RegroupOut:
    try:
        compiled = fp.compile_pattern(pattern)
    except fp.PatternError as exc:
        raise InvalidGroup(str(exc), constants.CODE_INVALID_PATTERN) from None
    plan = await _plan(db, collection, compiled, reassign)
    created = 0
    assigned = len(plan.changes)
    if plan.changes and not dry_run:
        keys = sorted({c[1] for c in plan.changes})
        groups, created = await _resolve(db, collection, keys)
        await _apply(db, collection, plan.changes, groups, reassign)
    elif plan.changes:
        stmt = select(Group.key).where(Group.collection_id == collection.id)
        existing = set((await db.execute(stmt)).scalars())
        created = len({c[1] for c in plan.changes} - existing)
    return RegroupOut(
        dry_run=dry_run,
        scanned=plan.scanned,
        matched=plan.matched,
        no_match=plan.no_match,
        timed_out=plan.timed_out,
        already_grouped=plan.already_grouped,
        unchanged=plan.unchanged,
        assigned=assigned,
        groups_created=created,
    )
