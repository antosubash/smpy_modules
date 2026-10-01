"""``python -m sm_records.cli export`` / ``import`` — the offline half of §16's
CSV/JSON import-export.

Same shape as :func:`sm_records.cli.reindex` and :func:`sm_records.cli.seed`:
this module owns the database connection and the argument parsing, and the
work itself is :mod:`sm_records.services.export` and
:mod:`sm_records.services.import_` — the *same* code the HTTP endpoints call,
so a file imported from the command line goes through the same validation,
the same relation checks, the same revisions and the same index writes as one
uploaded through the browser. A second, faster path here is how the two stop
agreeing about what a valid file is.

**This is the one caller allowed to commit.** In a request the framework's
session owns the transaction (``CLAUDE.md``), so nothing under ``services/``
may commit; here there is no request, so the command does it — and only after
a run that was asked to apply and came back without a refusal.

``--apply`` rather than ``--dry-run``: the default has to be the harmless one,
and a flag whose absence writes to every record of a type is the wrong
default to have typed twice.

**One tenant per run** (tenancy design §A.5, §H). ``--tenant`` (default
``default``) is bound around the whole command. Export reads that tenant's
type. Import writes into that tenant, and ignores any tenant a file claims.
That is what makes export from one tenant and import into another a way to
clone a type's records between tenants.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from sm_records.cli_common import add_tenant_argument, connected, load_settings
from sm_records.contracts.io import ImportFormat, ImportMode, ImportReport, OnError
from sm_records.services import export as export_service
from sm_records.services import import_ as import_service
from sm_records.services.errors import ImportRefused, RecordsError
from sm_records.services.types import get_type
from sm_records.tenancy import DEFAULT_TENANT, tenant_scope

__all__ = ["add_parsers", "export_command", "import_command"]

_FORMATS = tuple(item.value for item in ImportFormat)


async def export_command(
    database_url: str,
    type_key: str,
    fmt: str,
    out: str | None,
    tenant: str = DEFAULT_TENANT,
) -> int:
    """Stream one type to a file or to stdout, and return the byte count.

    Written a chunk at a time, never joined: the service streams precisely so
    a 100k-record type does not have to fit in memory, and ``"".join(...)``
    here would put it back.
    """
    async with connected(database_url) as db_state:
        with tenant_scope(tenant):
            settings = await load_settings(db_state)
            async with db_state.session_factory() as session:
                rtype = await get_type(session, type_key)
                type_id = int(rtype.id or 0)
            chosen = ImportFormat(fmt)
            stream = (
                export_service.iter_json if chosen is ImportFormat.JSON else export_service.iter_csv
            )
            # ``newline=""``: the CSV writer already emits RFC 4180's ``\r\n``,
            # and letting Python translate line endings on top of that produces
            # ``\r\r\n`` on a platform that translates.
            handle = (
                Path(out).open("w", encoding="utf-8", newline="")  # noqa: SIM115
                if out
                else sys.stdout
            )
            written = 0
            try:
                async for chunk in stream(db_state.session_factory, type_id, settings=settings):
                    handle.write(chunk)
                    written += len(chunk)
            finally:
                if out:
                    handle.close()
            if out:
                print(f"records export: {tenant}/{type_key} -> {out} ({written} bytes)")
            return written


def _print_report(type_key: str, report: ImportReport) -> None:
    mode = "dry run" if report.dry_run else "applied"
    print(
        f"records import: {type_key} — {report.total} row(s), "
        f"{report.created} created, {report.updated} updated, "
        f"{report.skipped} skipped, {report.failed} failed ({mode})"
    )
    for error in report.errors:
        where = f"row {error.row}" + (f" [{error.field}]" if error.field else "")
        print(f"  {where}: {error.message}")
    if report.errors_truncated:
        print(f"  … only the first {len(report.errors)} error(s) are listed")


async def import_command(
    database_url: str,
    type_key: str,
    path: str,
    *,
    mode: str,
    on_error: str,
    match_by: str,
    force: bool,
    apply: bool,
    tenant: str = DEFAULT_TENANT,
) -> ImportReport:
    """Import one file into ``tenant``. Writes nothing unless ``apply``."""
    text = Path(path).read_text(encoding="utf-8-sig")
    fmt = ImportFormat.CSV if path.lower().endswith(".csv") else ImportFormat.JSON
    options = import_service.ImportOptions(
        mode=ImportMode(mode),
        dry_run=not apply,
        on_error=OnError(on_error),
        match_by=match_by,
        force=force,
    )
    async with connected(database_url) as db_state:
        with tenant_scope(tenant):
            async with db_state.session_factory() as session:
                settings = await load_settings(db_state)
                rtype = await get_type(session, type_key)
                try:
                    report = await import_service.import_records(
                        session, rtype, text, fmt=fmt, options=options, settings=settings
                    )
                except ImportRefused as exc:
                    await session.rollback()
                    _print_report(type_key, exc.report)
                    raise SystemExit(1) from exc
                if apply:
                    # The one commit in this module — see the docstring. A dry
                    # run rolls back instead, because the validation pass reads
                    # and a session left open on a read transaction is a lock
                    # held for no reason.
                    await session.commit()
                else:
                    await session.rollback()
            _print_report(type_key, report)
            return report


def add_parsers(sub: Any) -> None:
    """Register ``export`` and ``import`` on ``cli.main``'s subparsers."""
    export = sub.add_parser("export", help="stream one type's records to JSON or CSV")
    export.add_argument("--type", dest="type_key", required=True, help="the record type's key")
    export.add_argument("--format", dest="fmt", choices=_FORMATS, default=ImportFormat.JSON.value)
    export.add_argument("--out", default=None, help="write here instead of stdout")
    export.add_argument("--database-url", dest="database_url", default=None)
    add_tenant_argument(export)

    imp = sub.add_parser("import", help="import a JSON or CSV file of records (dry run by default)")
    imp.add_argument("--type", dest="type_key", required=True, help="the record type's key")
    imp.add_argument("path", help="the .json or .csv file to import")
    imp.add_argument("--mode", choices=tuple(item.value for item in ImportMode), default="upsert")
    imp.add_argument(
        "--on-error",
        dest="on_error",
        choices=tuple(item.value for item in OnError),
        default="abort",
    )
    imp.add_argument("--match-by", dest="match_by", default="uuid")
    imp.add_argument(
        "--force",
        action="store_true",
        help="update records the file carries no version for (last write wins)",
    )
    imp.add_argument("--apply", action="store_true", help="actually write; omit for a dry run")
    imp.add_argument("--database-url", dest="database_url", default=None)
    add_tenant_argument(imp)


def run(args: Any, database_url: str) -> int:
    """Dispatch for ``cli.main``; returns the process exit code."""
    try:
        if args.command == "export":
            asyncio.run(
                export_command(database_url, args.type_key, args.fmt, args.out, args.tenant)
            )
            return 0
        asyncio.run(
            import_command(
                database_url,
                args.type_key,
                args.path,
                mode=args.mode,
                on_error=args.on_error,
                match_by=args.match_by,
                force=args.force,
                apply=args.apply,
                tenant=args.tenant,
            )
        )
    except RecordsError as exc:
        print(f"records {args.command}: {exc.detail}")
        return 1
    return 0
