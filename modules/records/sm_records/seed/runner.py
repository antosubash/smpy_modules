"""Batched, idempotent writing of the demo dataset through the real services.

Every record goes through :func:`sm_records.services.records.create_record`
— the same validation, uniqueness check, revision write and index write an
API call would trigger — so a seeded database is indistinguishable from one
built by hand through the admin UI. That is also why this is the slow path:
nothing here bypasses the per-record work the module always does.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from sm_records.index._analyze import analyze_tables, owned_table_names
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.seed import generate
from sm_records.seed._i18n import seed_translations
from sm_records.seed.log import log

# Split out for the file cap: how many records of each type a run writes is
# arithmetic with its own reasons, and this module is the writing.
from sm_records.seed.plan import distribute, weights_for
from sm_records.seed.types import active_type_defs
from sm_records.services.errors import NotFound
from sm_records.services.records import create_record
from sm_records.services.types import create_type, delete_type, get_type, record_count
from sm_records.settings import RecordsSettings

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


async def _ensure_types(db: Any, settings: RecordsSettings) -> dict[str, RecordType]:
    """Create the demo types that don't already exist, in dependency order
    (``active_type_defs``) — a relation's target must exist before the type
    naming it does (design doc §9), and that holds across a collection
    boundary too: ``event`` points at ``store`` (Phase 5 §6.4)."""
    types: dict[str, RecordType] = {}
    for type_def in active_type_defs():
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
                collection=type_def.collection,
                actor="records-seed-cli",
            )
            log(f"created type {type_def.key!r}")
        types[type_def.key] = rtype
    await db.commit()
    return types


async def _reset(db: Any) -> None:
    """Purge the demo types and their records, deepest referrer first.

    Reversing the list is exactly the safe order: ``event`` and ``order`` are
    never a relation's target, so they go first; ``store`` — which ``event``
    points at from another collection — only after; then ``product`` and
    ``contact``; ``company``, the one every other type may point at, last.
    ``delete_type`` itself purges (hard-deletes, trash included) before
    dropping the row, so this really empties the tables rather than leaving
    soft-deleted rows behind.
    """
    for type_def in reversed(active_type_defs()):
        try:
            rtype = await get_type(db, type_def.key)
        except NotFound:
            continue
        held = await record_count(db, rtype, include_deleted=True)
        await delete_type(db, rtype, confirm_record_count=held)
        log(f"reset: deleted type {type_def.key!r} ({held} record(s))")
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
            log(f"{self._count}/{self._total_planned} records written")

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
    weights = weights_for({td.key for td in active_type_defs()})
    counts = distribute(records, weights)
    summary = SeedSummary(reset=reset)

    async with db_state.session_factory() as db:
        if reset:
            await _reset(db)
        types = await _ensure_types(db, settings)

        offsets = {key: await record_count(db, types[key], include_deleted=True) for key in weights}
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
        summary.created["company"] += await seed_translations(
            db, committer, types["company"], companies, settings=settings
        )

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

        # The collection's type, last and only when the host declared it. It
        # goes through exactly the same ``create_record`` as the five above —
        # the only difference is which tables ``tables_for`` hands the writer
        # (Phase 5 §6.3), which is the point.
        if "event" in counts:
            events = 0
            store_uuids = [store.uuid for store in stores]
            for i in range(counts["event"]):
                venue = rng.choice(store_uuids) if store_uuids else None
                payload, slug = generate.gen_event(rng, offsets["event"] + i, store_uuid=venue)
                await _create(db, committer, types["event"], payload, settings=settings, slug=slug)
                events += 1
            summary.created["event"] = events

        await committer.finish()
        # A bulk load is exactly the state SQLite has no statistics for, and a
        # seeded database's first act is to be queried. One pass here, out of
        # any request, is worth orders of magnitude on the filters that read
        # the index tables — see :mod:`sm_records.index._analyze`.
        await analyze_tables(db, owned_table_names())
        await db.commit()

    summary.elapsed_seconds = time.monotonic() - started
    log(
        f"done: {summary.total} record(s) in {summary.elapsed_seconds:.1f}s "
        f"({summary.records_per_second:.0f}/s) — {summary.created}"
    )
    return summary
