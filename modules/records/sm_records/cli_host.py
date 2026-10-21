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
``app.state.sm.event_bus`` to the write. That is the bus every module filled in
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
from contextlib import asynccontextmanager
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


def resolve_database_url(app: Any, given: str | None, default: Any) -> str:
    """The database a command writes to.

    With an app, the app's: its subscribers read and write through its own
    engine, and a write to one database announced to subscribers watching
    another is worse than no announcement. ``--database-url`` may restate it,
    not contradict it. ``default`` is called only when neither says.
    """
    if app is None:
        return given or default()
    url = str(app.state.sm.settings.database_url)
    if given is not None and given != url:
        raise SystemExit(
            f"--database-url {given!r} is not the database --app writes to ({url!r}); "
            "drop one of them"
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

    A command that fails (a refused import exits through ``SystemExit``) still
    leaves the lifespan the normal way before the failure propagates: the
    framework's lifespan has no ``finally``, so an exception thrown into it
    would skip every module's ``on_shutdown`` — the scheduler that
    pagebuilder started would never be stopped, nor the engine disposed.
    """
    if app is None:
        warn_no_bus(command)
        yield None
        return
    failure: BaseException | None = None
    async with app.router.lifespan_context(app):
        try:
            yield app.state.sm.event_bus
        except (Exception, SystemExit) as exc:
            failure = exc
    if failure is not None:
        raise failure
