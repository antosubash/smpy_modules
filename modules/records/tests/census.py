"""The statement census: a tripwire for a records statement that forgot its tenant.

Tenancy design K12. The framework's tenant filter reaches only mappers in a
statement's top-level columns (FACT 1c, 1d); Core statements over ``__table__``,
``text()``, ``update()``/``delete()`` and ``count().select_from()`` get nothing,
which is why §E makes an explicit ``tenant_id`` predicate mandatory on them.
Nothing *checks* that rule except review. This does, suite-wide: every SQL
statement that names a tenant-owned table (``records_type``,
``records_type_revision``, and every table set's ``…_record``/``…_revision``)
must mention ``tenant_id`` somewhere, unless it is one of:

* tagged :data:`~sm_records.tenancy.ALL_TENANTS` — a deliberate cross-tenant
  read (``_cross_tenant.read_all``, which every such read goes through);
* the unit of work writing or refreshing one object by primary key
  (``WHERE <t>.id = :p``, optionally ``AND <t>.version = :p``, sent from
  SQLAlchemy's ``orm/persistence.py`` or ``orm/loading.py``) — an object the
  session loaded under the bound tenant, and that the guard's ``before_flush``
  refuses unbound. A by-id statement a service builds itself is not exempt;
* sent by **test** code rather than by ``sm_records``: a fixture that forges a
  row, the database reset. Where a statement came from is read off the call
  stack, walked across SQLAlchemy's greenlet into the awaiting coroutines,
  and the innermost frame that is either ``sm_records`` or ``tests`` decides.

A tripwire, not a proof: it cannot tell which of two owned tables in one
statement the ``tenant_id`` belongs to, and a subquery that shares a statement
with a filtered top-level table passes. The isolation matrix
(``test_tenancy_isolation*.py``) covers those by effect.

**When it runs.** On Postgres by default — the design's "Postgres job" — and
on SQLite only when ``RECORDS_CENSUS=1``; ``RECORDS_CENSUS=0`` turns it off
anywhere. ``RECORDS_CENSUS_LOG=<path>`` appends every statement it catches,
test-side ones included, for a report.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import greenlet
from sm_records.tenancy import ALL_TENANTS
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.pg_support import USING_POSTGRES

__all__ = ["Census", "census_enabled"]

_PACKAGE_DIR = str(Path(__file__).resolve().parents[1] / "sm_records") + os.sep
_TESTS_DIR = str(Path(__file__).resolve().parent) + os.sep

OWNED = re.compile(
    r"\b(records_type(?:_revision)?|records(?:_c_[a-z0-9_]+?)?_(?:record|revision))\b"
)
"""A tenant-owned table's name, global set or collection (design §B)."""

_PARAM = r"(?:\?|\$\d+(?:::\w+)?|%\(\w+\)s)"
_BY_PRIMARY_KEY = re.compile(rf"^\w+\.id = {_PARAM}(?: AND \w+\.version = {_PARAM})?$")
_DML = ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")


def census_enabled() -> bool:
    flag = os.environ.get("RECORDS_CENSUS")
    return USING_POSTGRES if flag is None else flag not in ("", "0", "false", "off")


def _where(sql: str) -> str:
    return sql.rsplit(" WHERE ", 1)[1] if " WHERE " in sql else ""


_UOW_FILES = (f"orm{os.sep}persistence.py", f"orm{os.sep}loading.py")


def _unit_of_work() -> bool:
    """The statement is the ORM's own — a flush (``persistence``) or an
    expired-attribute refresh (``loading``) — not a by-id ``update()`` or
    ``select()`` a service wrote, which gets no exemption."""
    frame: Any = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename.endswith(_UOW_FILES):
            return True
        frame = frame.f_back
    return False


def _origin() -> tuple[str, str]:
    """``("service" | "test" | "other", "file:line")`` — the innermost frame,
    across greenlets, that belongs to the module or to its tests."""
    frame: Any = sys._getframe(2)
    current = greenlet.getcurrent()
    while True:
        while frame is not None:
            name = frame.f_code.co_filename
            if name.startswith(_PACKAGE_DIR):
                return "service", f"{name[len(_PACKAGE_DIR) :]}:{frame.f_lineno}"
            if name.startswith(_TESTS_DIR):
                return "test", f"tests/{name[len(_TESTS_DIR) :]}:{frame.f_lineno}"
            frame = frame.f_back
        current = current.parent
        if current is None:
            return "other", "?"
        frame = current.gr_frame


@dataclass
class Census:
    """Installed once per session; read and emptied by one test at a time."""

    caught: list[tuple[str, str]] = field(default_factory=list)
    test_side: list[tuple[str, str]] = field(default_factory=list)
    log: str | None = field(default_factory=lambda: os.environ.get("RECORDS_CENSUS_LOG"))

    def install(self) -> None:
        event.listen(Engine, "before_cursor_execute", self._check)

    def remove(self) -> None:
        event.remove(Engine, "before_cursor_execute", self._check)

    def _check(self, _conn, _cursor, statement, _params, context, _many) -> None:
        sql = " ".join(statement.split())
        if not sql.upper().startswith(_DML) or "tenant_id" in sql or not OWNED.search(sql):
            return
        if context is not None and context.execution_options.get(ALL_TENANTS):
            return
        if _BY_PRIMARY_KEY.match(_where(sql)) and _unit_of_work():
            return
        kind, where = _origin()
        (self.caught if kind == "service" else self.test_side).append((where, sql))

    def take(self, test_id: str) -> list[tuple[str, str]]:
        """This test's service-side catches; both kinds go to the log."""
        caught, self.caught = self.caught, []
        test_side, self.test_side = self.test_side, []
        if self.log and (caught or test_side):
            with Path(self.log).open("a", encoding="utf-8") as out:
                for kind, rows in (("SERVICE", caught), ("test", test_side)):
                    for where, sql in rows:
                        out.write(f"{kind}\t{test_id}\t{where}\t{sql[:400]}\n")
        return caught
