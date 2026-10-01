"""``python -m sm_records.cli reindex [--type KEY]`` / ``seed`` / ``export`` /
``import`` / ``tenants`` — design doc §7.7, §8.9, the demo-data seeder in
``sm_records/seed/``, §16's file import-export, and the tenancy design's §J.

The recovery path for an index that is wrong, and the other half of "deferred"
in a repo with no queue: a background task that died with its worker leaves
``reindex_pending`` set, and this is what finishes it. Safe to run live and
safe to run twice — the rebuild deletes and rewrites each record's rows from
``data``, which is the source of truth (§7.7).

This file parses and dispatches. The work lives next to it:
:mod:`sm_records.cli_reindex` (``reindex``), :mod:`sm_records.cli_verify`
(``reindex --verify``, which writes nothing and exits ``1`` on drift),
:mod:`sm_records.cli_io` (``export``/``import``), and
:mod:`sm_records.cli_common` for the connection and ``--tenant``, which every
subcommand takes. ``tenants`` is read-only and lives here, because it is only
a query and a table.

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

from sm_records import cli_io
from sm_records._cross_tenant import TenantCounts, tenant_counts
from sm_records.cli_common import add_tenant_argument, connected, load_settings
from sm_records.cli_reindex import force_pending, reindex, run_verify
from sm_records.seed.runner import SeedSummary
from sm_records.tenancy import DEFAULT_TENANT, tenant_scope

__all__ = ["main", "reindex", "run_verify", "seed", "tenants"]


async def seed(
    database_url: str,
    *,
    records: int,
    seed_value: int,
    reset: bool,
    tenant: str = DEFAULT_TENANT,
) -> SeedSummary:
    """Create the demo types (if missing) and write ``records`` records.

    Delegates entirely to :mod:`sm_records.seed` — this wrapper only owns the
    database connection and the tenant, the same division of labour as
    :func:`reindex`, so :func:`sm_records.seed.seed_database` stays callable
    in-process (a test, a perf harness) without a subprocess or a
    settings-from-env detour.

    Everything runs inside ``tenant_scope(tenant)``. So ``--reset`` sees, and
    deletes, only that tenant's demo types: another tenant's ``company`` is a
    different row that the type lookup under this scope never returns.
    """
    from sm_records.seed import seed_database

    async with connected(database_url) as db_state:
        settings = await load_settings(db_state)
        with tenant_scope(tenant):
            summary = await seed_database(
                db_state, settings, records=records, seed=seed_value, reset=reset
            )
        print(
            f"records seed: {summary.total} record(s) in tenant {tenant!r} in "
            f"{summary.elapsed_seconds:.1f}s ({summary.records_per_second:.0f}/s)"
        )
        for key, count in summary.created.items():
            print(f"records seed: {tenant}/{key} — {count}")
        return summary


async def tenants(database_url: str) -> dict[str, TenantCounts]:
    """``records tenants``: every tenant that holds a type, with its counts.

    Read-only, and across tenants by construction
    (:mod:`sm_records._cross_tenant`). Records never creates a tenant. A
    tenant exists when a user, a header or ``--tenant`` names it and something
    is written, so this is the only list of tenants there is (§J).
    """
    async with connected(database_url) as db_state, db_state.session_factory() as session:
        counts = await tenant_counts(session)
    if not counts:
        print("records tenants: no record types in any tenant")
        return counts
    width = max(len("tenant"), *(len(tenant) for tenant in counts))
    print(f"{'tenant':<{width}}  {'types':>6}  {'records':>9}  {'trashed':>9}")
    for tenant, c in counts.items():
        print(f"{tenant:<{width}}  {c.types:>6}  {c.records:>9}  {c.trashed:>9}")
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sm_records.cli",
        description="Records module maintenance commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # ``export``/``import`` live in ``cli_io`` — the same 300-line cap that
    # split ``seed`` into its own package, and the same division: this file
    # parses and dispatches, the other owns the work.
    cli_io.add_parsers(sub)
    reindex_parser = sub.add_parser(
        "reindex", help="rebuild index rows from documents (design doc §7.7)"
    )
    reindex_parser.add_argument(
        "--type",
        dest="type_key",
        default=None,
        help="one record type's key; omit to finish every pending rebuild",
    )
    add_tenant_argument(reindex_parser, every_tenant=True)
    reindex_parser.add_argument("--database-url", dest="database_url", default=None)
    reindex_parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "check the reduce indexes against the records instead of rebuilding; "
            "exit 1 if any stored group disagrees (Phase 5 §5.2)"
        ),
    )
    seed_parser = sub.add_parser(
        "seed", help="write demo data (company/contact/product/order/store records)"
    )
    seed_parser.add_argument(
        "--records",
        type=int,
        default=5000,
        help="total record count across all five demo types (default: 5000)",
    )
    seed_parser.add_argument(
        "--seed",
        dest="seed_value",
        type=int,
        default=42,
        help="RNG seed; the same value regenerates the same dataset (default: 42)",
    )
    seed_parser.add_argument(
        "--reset",
        action="store_true",
        help="purge the demo types and their records first, then reseed from empty",
    )
    seed_parser.add_argument(
        "--database-url",
        dest="database_url",
        default=None,
        help="override SM_DATABASE_URL / .env for this run",
    )
    add_tenant_argument(seed_parser)
    tenants_parser = sub.add_parser(
        "tenants", help="list the tenants holding record types, with counts (read-only)"
    )
    tenants_parser.add_argument("--database-url", dest="database_url", default=None)
    args = parser.parse_args(argv)

    from simple_module_hosting.settings import Settings

    database_url = args.database_url or Settings().database_url
    if args.command in ("export", "import"):
        return cli_io.run(args, database_url)

    if args.command == "seed":
        asyncio.run(
            seed(
                database_url,
                records=args.records,
                seed_value=args.seed_value,
                reset=args.reset,
                tenant=args.tenant,
            )
        )
        return 0

    if args.command == "tenants":
        asyncio.run(tenants(database_url))
        return 0

    if args.verify:
        # Read-only, and never combined with the rebuild: "check it" and "fix
        # it" are different intentions, and a command that silently did both
        # would make the drift it repaired impossible to report.
        return 1 if asyncio.run(run_verify(database_url, args.type_key, args.tenant)) else 0
    if args.type_key is not None:
        force_pending(database_url, args.type_key, args.tenant or DEFAULT_TENANT)
    asyncio.run(reindex(database_url, args.type_key, args.tenant))
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    sys.exit(main())
