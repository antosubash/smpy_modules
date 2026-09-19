"""Batched, idempotent writing of the demo dataset through the real services.

Every record goes through :func:`sm_records.services.records.create_record`
— the same validation, uniqueness check, revision write and index write an
API call would trigger — so a seeded database is indistinguishable from one
built by hand through the admin UI. That is also why this is the slow path:
nothing here bypasses the per-record work the module always does.
"""

from __future__ import annotations

import math
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from sm_records.models import Record, RecordStatus, RecordType
from sm_records.seed import generate
from sm_records.seed.types import TYPE_DEFS
from sm_records.services.errors import NotFound
from sm_records.services.records import create_record
from sm_records.services.types import create_type, delete_type, get_type, record_count
from sm_records.settings import RecordsSettings

#: Total record count is split across the five types by these weights
#: (task spec: 5% / 25% / 15% / 45% / 10%), each type getting at least one
#: record regardless of how small ``records`` is.
_WEIGHTS: dict[str, float] = {
    "company": 0.05,
    "contact": 0.25,
    "product": 0.15,
    "store": 0.10,
    "order": 0.45,
}

_BATCH_SIZE = 200


@dataclass(slots=True)
class SeedSummary:
    """What a seeding run produced — the CLI prints this, a caller inspects it."""

    created: dict[str, int] = field(default_factory=dict)
    reset: bool = False
    elapsed_seconds: float = 0.0

    @property
    def total(self) -> int:
        return sum(self.created.values())

    @property
    def records_per_second(self) -> float:
        return self.total / self.elapsed_seconds if self.elapsed_seconds > 0 else float(self.total)


def _distribute(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Split ``total`` across ``weights``' keys, each getting at least one.

    Largest-remainder rounding: floor every share, hand out the leftover to
    the keys with the biggest fractional part, and — for a ``total`` too
    small to give every key its floor plus its forced minimum of one — claw
    back from the keys least entitled to the extra. Exact for any
    ``total >= len(weights)``, which every sane invocation satisfies.
    """
    keys = list(weights)
    if total <= 0:
        return dict.fromkeys(keys, 0)
    if total < len(keys):
        return {key: (1 if i < total else 0) for i, key in enumerate(keys)}

    raw = {key: total * weight for key, weight in weights.items()}
    counts = {key: max(1, math.floor(raw[key])) for key in keys}
    diff = total - sum(counts.values())

    by_frac_desc = sorted(keys, key=lambda k: raw[k] - math.floor(raw[k]), reverse=True)
    by_frac_asc = list(reversed(by_frac_desc))
    i = 0
    while diff > 0:
        counts[by_frac_desc[i % len(keys)]] += 1
        diff -= 1
        i += 1
    i = 0
    while diff < 0:
        key = by_frac_asc[i % len(keys)]
        if counts[key] > 1:
            counts[key] -= 1
            diff += 1
        i += 1
    return counts


def _log(message: str) -> None:
    print(f"records seed: {message}", file=sys.stderr)


async def _ensure_types(db: Any, settings: RecordsSettings) -> dict[str, RecordType]:
    """Create the five demo types that don't already exist, in dependency
    order (``TYPE_DEFS``) — a relation's target must exist before the type
    naming it does (design doc §9)."""
    types: dict[str, RecordType] = {}
    for type_def in TYPE_DEFS:
        try:
            rtype = await get_type(db, type_def.key)
        except NotFound:
            rtype = await create_type(
                db,
                key=type_def.key,
                label=type_def.label,
                label_plural=type_def.label_plural,
                settings=settings,
                fields_raw=type_def.fields,
                display_field=type_def.display_field,
                slug_field=type_def.slug_field,
                actor="records-seed-cli",
            )
            _log(f"created type {type_def.key!r}")
        types[type_def.key] = rtype
    await db.commit()
    return types


async def _reset(db: Any) -> None:
    """Purge the five demo types and their records, deepest referrer first.

    Reversing ``TYPE_DEFS`` is exactly the safe order: ``order`` and ``store``
    are never a relation's target among these five, so they can go first;
    ``product`` and ``contact`` only after; ``company`` — the one every other
    type may point at — last. ``delete_type`` itself purges (hard-deletes,
    trash included) before dropping the row, so this really empties the
    tables rather than leaving soft-deleted rows behind.
    """
    for type_def in reversed(TYPE_DEFS):
        try:
            rtype = await get_type(db, type_def.key)
        except NotFound:
            continue
        held = await record_count(db, rtype, include_deleted=True)
        await delete_type(db, rtype, confirm_record_count=held)
        _log(f"reset: deleted type {type_def.key!r} ({held} record(s))")
    await db.commit()


class _BatchCommitter:
    """Commits every ``_BATCH_SIZE`` records and prints progress to stderr.

    ``AsyncSession`` here has ``expire_on_commit=False`` (see
    ``simple_module_db.session.init_db``), so objects created before a commit
    — a company a later contact still needs the uuid of — stay usable after
    it without a refresh.
    """

    def __init__(self, db: Any, total_planned: int) -> None:
        self._db = db
        self._total_planned = total_planned
        self._count = 0

    async def tick(self) -> None:
        self._count += 1
        if self._count % _BATCH_SIZE == 0:
            await self._db.commit()
            _log(f"{self._count}/{self._total_planned} records written")

    async def finish(self) -> None:
        await self._db.commit()


async def _create(
    db: Any,
    committer: _BatchCommitter,
    rtype: RecordType,
    data: dict[str, Any],
    *,
    settings: RecordsSettings,
    slug: str | None,
) -> Record:
    record = await create_record(
        db,
        rtype,
        data=data,
        settings=settings,
        status=RecordStatus.PUBLISHED,
        slug=slug,
        actor="records-seed-cli",
    )
    await committer.tick()
    return record


async def run(
    db_state: Any,
    settings: RecordsSettings,
    *,
    records: int,
    seed: int,
    reset: bool,
) -> SeedSummary:
    """The whole seeding run: optional reset, ensure types, generate records.

    One session for the entire run (matching ``cli.py reindex``'s shape) —
    ``expire_on_commit=False`` makes that safe across the periodic commits a
    :class:`_BatchCommitter` issues.
    """
    started = time.monotonic()
    rng = random.Random(seed)
    counts = _distribute(records, _WEIGHTS)
    summary = SeedSummary(reset=reset)

    async with db_state.session_factory() as db:
        if reset:
            await _reset(db)
        types = await _ensure_types(db, settings)

        offsets = {
            key: await record_count(db, types[key], include_deleted=True) for key in _WEIGHTS
        }
        committer = _BatchCommitter(db, records)

        companies: list[Record] = []
        for i in range(counts["company"]):
            payload, slug = generate.gen_company(rng, offsets["company"] + i)
            companies.append(
                await _create(
                    db, committer, types["company"], payload, settings=settings, slug=slug
                )
            )
        summary.created["company"] = len(companies)

        contacts: list[Record] = []
        for i in range(counts["contact"]):
            company_uuid = rng.choice(companies).uuid if companies else None
            payload = generate.gen_contact(rng, offsets["contact"] + i, company_uuid=company_uuid)
            contacts.append(
                await _create(
                    db, committer, types["contact"], payload, settings=settings, slug=None
                )
            )
        summary.created["contact"] = len(contacts)

        products: list[Record] = []
        for i in range(counts["product"]):
            payload = generate.gen_product(rng, offsets["product"] + i)
            products.append(
                await _create(
                    db, committer, types["product"], payload, settings=settings, slug=None
                )
            )
        summary.created["product"] = len(products)

        stores: list[Record] = []
        for i in range(counts["store"]):
            manager_uuid = rng.choice(contacts).uuid if contacts else None
            payload, slug = generate.gen_store(rng, offsets["store"] + i, manager_uuid=manager_uuid)
            stores.append(
                await _create(db, committer, types["store"], payload, settings=settings, slug=slug)
            )
        summary.created["store"] = len(stores)

        product_uuids = [product.uuid for product in products]
        orders = 0
        for i in range(counts["order"]):
            customer_uuid = rng.choice(contacts).uuid
            payload = generate.gen_order(
                rng,
                offsets["order"] + i,
                customer_uuid=customer_uuid,
                product_uuids=product_uuids,
            )
            await _create(db, committer, types["order"], payload, settings=settings, slug=None)
            orders += 1
        summary.created["order"] = orders

        await committer.finish()

    summary.elapsed_seconds = time.monotonic() - started
    _log(
        f"done: {summary.total} record(s) in {summary.elapsed_seconds:.1f}s "
        f"({summary.records_per_second:.0f}/s) — {summary.created}"
    )
    return summary
