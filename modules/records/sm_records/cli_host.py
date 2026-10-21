"""``--app MODULE:ATTR`` — the host's event subscribers for a CLI write (GH #157).

``python -m sm_records.cli seed`` and ``import --apply`` publish through
:mod:`sm_records.events`, to whatever bus the session carries. A standalone
process has no host, so without this it carries none: the records are written,
and no subscriber the host registered ever hears about them.

``--app`` names the host's ASGI app the way ``uvicorn`` does (``main:app``,
with ``--app-dir host`` for the demo host), or a zero-argument factory that
returns one (``simple_module_hosting:create_app`` builds the framework's app
from the installed modules without a host file at all). The CLI imports it and
runs its **lifespan** — not its HTTP server — around the command, then hands
``app.state.sm.event_bus`` to the write, which goes through the app's own
``app.state.sm.db`` rather than an engine of the CLI's: the session listeners,
tenant settings and pool the app configured, and with ``:memory:`` SQLite the
same database at all. That is the bus every module filled in
``register_event_handlers``, in the state its ``on_startup`` left it: settings
hydrated from the database, the tenancy mode fixed, and anything a subscriber
closes over in place. Building a bare bus and calling each module's
``register_event_handlers`` would skip the lifespan, and a subscriber written
against a booted app would run against one that never started. The cost is the
host's own: its migration check refuses a database behind head, and a module
that starts a background task on startup (pagebuilder's scheduler) runs it for
the length of the command.

The module imports nothing of any host: the app is whatever the operator
names, resolved at run time.

Without ``--app`` the write still happens and :func:`warn_no_bus` says, on
stderr, what was skipped. No reindex is owed afterwards: the record, its
revisions and its index rows are written inline by the services whether or not
anything is listening, so what a bus-less write skips is exactly the host's
subscribers and nothing of this module's own.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

__all__ = ["add_app_arguments", "host_bus", "load_app", "resolve_database_url", "warn_no_bus"]


def add_app_arguments(parser: Any) -> None:
    """``--app`` and ``--app-dir`` on a subcommand that writes records."""
    parser.add_argument(
        "--app",
        dest="app",
        default=None,
        metavar="MODULE:ATTR",
        help=(
            "the host's ASGI app (or a factory returning one), e.g. main:app; its "
            "lifespan runs around the command so its event subscribers hear the writes"
        ),
    )
    parser.add_argument(
        "--app-dir",
        dest="app_dir",
        default=None,
        help="directory to import --app from, prepended to sys.path (the demo host: host)",
    )


def load_app(spec: str, app_dir: str | None = None) -> Any:
    """Import ``MODULE:ATTR`` and return the SimpleModule app it names.

    ``SystemExit`` with a message, never a traceback, for a spec that is not
    one: this is an operator's typo far more often than a bug.
    """
    module_name, sep, attr = spec.partition(":")
    if not (sep and module_name and attr):
        raise SystemExit(f"--app {spec!r}: expected MODULE:ATTR, e.g. main:app")
    if app_dir is not None:
        sys.path.insert(0, str(Path(app_dir).resolve()))
    try:
        target: Any = importlib.import_module(module_name)
    except ImportError as exc:
        raise SystemExit(f"--app {spec!r}: cannot import {module_name!r} ({exc})") from exc
    for part in attr.split("."):
        if not hasattr(target, part):
            raise SystemExit(f"--app {spec!r}: {module_name!r} has no attribute {attr!r}")
        target = getattr(target, part)
    if not hasattr(target, "router") and callable(target):
        target = target()  # a factory, ``create_app`` style
    services = getattr(getattr(target, "state", None), "sm", None)
    if getattr(services, "event_bus", None) is None or not hasattr(target, "router"):
        raise SystemExit(f"--app {spec!r}: not a SimpleModule app (no app.state.sm.event_bus)")
    return target


def _normalised(raw: str) -> tuple[Any, ...]:
    """``raw`` reduced to what names a database, however it was spelled.

    Parsed rather than compared as text: percent-escaping and query order
    differ between spellings of one URL, and the framework rewrites a relative
    SQLite path to an absolute one under the project root (the directory that
    holds ``.env``), so ``./host/app.db`` restates ``/repo/host/app.db``.
    """
    from simple_module_core.dotenv import find_env_file
    from sqlalchemy.engine import make_url

    url = make_url(raw)
    database = url.database
    if (
        url.get_backend_name() == "sqlite"
        and database
        and database != ":memory:"
        and not database.startswith("file:")
    ):
        path = Path(database)
        if not path.is_absolute():
            path = find_env_file().parent / path
        database = str(path.resolve())
    query = tuple(sorted((key, str(value)) for key, value in url.query.items()))
    return (url.drivername, url.username, url.password, url.host, url.port, database, query)


def _shown(raw: str) -> str:
    """``raw`` as it is safe to print: the password masked."""
    from sqlalchemy.engine import make_url

    return make_url(raw).render_as_string(hide_password=True)


def resolve_database_url(app: Any, given: str | None, default: Any) -> str:
    """The database a command writes to.

    With an app, the app's: the command writes through the app's own engine
    (:func:`sm_records.cli_common.connected`), so ``--database-url`` may
    restate that database but never name another — a write to one database
    announced to subscribers watching another is worse than no announcement.
    ``default`` is called only when neither says. A refusal never prints a
    password.
    """
    if app is None:
        return given or default()
    url = str(app.state.sm.settings.database_url)
    if given is None:
        return url
    from sqlalchemy.exc import ArgumentError

    try:
        same = _normalised(given) == _normalised(url)
    except ArgumentError as exc:
        raise SystemExit("--database-url is not a database URL") from exc
    if not same:
        raise SystemExit(
            f"--database-url {_shown(given)} is not the database --app writes to "
            f"({_shown(url)}); drop one of them"
        )
    return url


def warn_no_bus(command: str) -> None:
    """Say, loudly and on stderr, that this write reaches no subscriber."""
    print(
        f"records {command}: WARNING: no --app given, so these writes reach no event "
        "subscriber.\n"
        "  Records, revisions and index rows are written as usual. Skipped: every "
        "handler the host\n"
        "  subscribes to RecordCreated, RecordUpdated, RecordPurged or RecordTypeDeleted "
        "(see the\n"
        "  records README, 'Subscribing to what records do'). Pass the host's app to "
        "publish to them:\n"
        f"  python -m sm_records.cli {command} ... --app main:app --app-dir host",
        file=sys.stderr,
    )


@asynccontextmanager
async def host_bus(app: Any, command: str) -> AsyncIterator[Any]:
    """The host's bus for the length of the block, or ``None`` after a warning.

    The lifespan is entered on the running loop — the one the write and its
    subscribers run on — and left after the write has committed, so every
    ``on_commit`` publish happens while the app is still up.

    Whatever ends the block — a refused import's ``SystemExit``, an error, the
    ``CancelledError`` that ``asyncio.run`` turns Ctrl-C into, a
    ``KeyboardInterrupt`` — the lifespan is left the *normal* way first, and
    the failure re-raised after: the framework's lifespan has no ``finally``,
    so an exception thrown into it would skip every module's ``on_shutdown``
    (pagebuilder's scheduler never stopped) and the engine's disposal. If the
    shutdown itself fails, the original failure is still the one raised.

    A startup that fails part-way is the one case this cannot fully repair. The
    framework does not undo the hooks that ran before the failing one, and
    running ``on_shutdown`` for modules that may never have started is not ours
    to do, so this disposes the engine and re-raises; a task an earlier hook
    started is cancelled with the event loop when ``asyncio.run`` returns.
    """
    if app is None:
        warn_no_bus(command)
        yield None
        return
    lifespan = app.router.lifespan_context(app)
    try:
        await lifespan.__aenter__()
    except BaseException:
        await _dispose_engine(app)
        raise
    failure: BaseException | None = None
    try:
        yield app.state.sm.event_bus
    except BaseException as exc:
        failure = exc
    try:
        await lifespan.__aexit__(None, None, None)
    finally:
        if failure is not None:
            raise failure


async def _dispose_engine(app: Any) -> None:
    """Dispose the app's engine after a failed startup, never masking that failure."""
    engine = getattr(getattr(app.state.sm, "db", None), "engine", None)
    if engine is not None:
        with suppress(Exception):  # the startup failure is the one worth reporting
            await engine.dispose()
