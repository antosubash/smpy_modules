"""``python -m sm_records.cli reindex [--type KEY]`` — design doc §7.7, §8.9.

The recovery path for an index that is wrong, and the other half of "deferred"
in a repo with no queue: a background task that died with its worker leaves
``reindex_pending`` set, and this is what finishes it. Safe to run live and
safe to run twice — the rebuild deletes and rewrites each record's rows from
``data``, which is the source of truth (§7.7).

``argparse`` rather than typer: this ships in a published module, and a CLI
that is two flags wide does not justify a dependency a host would have to
carry. Run it from the repo root, like every other entry point here, so the
root ``.env`` is what ``SM_DATABASE_URL`` comes from.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy import select

from sm_records.constants import PACKAGE
from sm_records.models import RecordType
from sm_records.services.reindex_runner import pending_type_ids, run_pending
from sm_records.settings import RecordsSettings


async def _load_settings(db_state) -> RecordsSettings:
    """The module's settings as the running host would see them.

    They live in the database (``CLAUDE.md``: no ``SM_RECORDS_*`` env var
    exists), so the CLI reads the same overrides the Settings screen writes —
    ``reindex_batch_size`` in particular, which an operator will have tuned for
    exactly this command. A host whose settings tables are not there yet, or a
    module never registered, falls back to the declared defaults rather than
    refusing to reindex.
    """
    try:
        from settings.hydrate import hydrate_settings
        from settings.service import SettingService
        from settings.store import SettingsStore

        async with db_state.session_factory() as session:
            store = SettingsStore(SettingService(session))
            return await hydrate_settings(RecordsSettings, store, PACKAGE)
    except Exception as exc:  # pragma: no cover - depends on the host's install
        print(f"warning: using default settings ({exc.__class__.__name__}: {exc})")
        return RecordsSettings()


async def _types_to_run(db_state, type_key: str | None) -> list[tuple[int, str]]:
    async with db_state.session_factory() as session:
        if type_key is not None:
            row = (
                (await session.execute(select(RecordType).where(RecordType.key == type_key)))
                .scalars()
                .first()
            )
            if row is None:
                raise SystemExit(f"no record type with key {type_key!r}")
            return [(int(row.id), row.key)]
        ids = await pending_type_ids(session)
        rows = (await session.execute(select(RecordType.id, RecordType.key))).all()
        keys = {int(i): k for i, k in rows if i is not None}
        return [(type_id, keys.get(type_id, "?")) for type_id in ids]


async def reindex(database_url: str, type_key: str | None) -> int:
    """Run every pending rebuild (or one named type's) and print a summary.

    A type named explicitly is run even if nothing is pending: that is the
    "the index is wrong, rebuild it" case of §7.7, which is not driven by a
    marker. Without ``--type`` only the types carrying markers are visited,
    because walking every record of every type is not what an operator
    recovering one stuck field asked for.
    """
    db_state = init_db(database_url)
    register_listeners(db_state)
    try:
        settings = await _load_settings(db_state)
        targets = await _types_to_run(db_state, type_key)
        if not targets:
            print("records reindex: nothing pending")
            return 0
        total = 0
        for type_id, key in targets:
            count = await run_pending(db_state, type_id, settings=settings)
            total += count
            print(f"records reindex: {key} — {count} record(s)")
        print(f"records reindex: {total} record(s) across {len(targets)} type(s)")
        return total
    finally:
        await db_state.engine.dispose()


def _force_pending(database_url: str, type_key: str) -> None:
    """``--type`` on a type with no markers: mark the whole type, then run.

    Written as a marker rather than as a second code path through the runner,
    so the rebuild an operator triggers by hand is the identical operation a
    schema change triggers — including being resumable if this process dies
    halfway through it.
    """
    from sm_records.constants import REINDEX_ALL
    from sm_records.services._common import mark_written, utcnow

    async def run() -> None:
        db_state = init_db(database_url)
        register_listeners(db_state)
        try:
            async with db_state.session_factory() as session:
                rtype = (
                    (await session.execute(select(RecordType).where(RecordType.key == type_key)))
                    .scalars()
                    .first()
                )
                if rtype is None:
                    raise SystemExit(f"no record type with key {type_key!r}")
                pending = dict(rtype.reindex_pending or {})
                pending.setdefault(REINDEX_ALL, utcnow().isoformat())
                for raw in rtype.fields or []:
                    if raw.get("indexed"):
                        pending.setdefault(str(raw.get("key")), utcnow().isoformat())
                rtype.reindex_pending = pending
                session.add(rtype)
                mark_written(session)
                await session.commit()
        finally:
            await db_state.engine.dispose()

    asyncio.run(run())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sm_records.cli",
        description="Records module maintenance commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    reindex_parser = sub.add_parser(
        "reindex", help="rebuild index rows from documents (design doc §7.7)"
    )
    reindex_parser.add_argument(
        "--type",
        dest="type_key",
        default=None,
        help="one record type's key; omit to finish every pending rebuild",
    )
    args = parser.parse_args(argv)

    from simple_module_hosting.settings import Settings

    database_url = Settings().database_url
    if args.type_key is not None:
        _force_pending(database_url, args.type_key)
    asyncio.run(reindex(database_url, args.type_key))
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    sys.exit(main())
