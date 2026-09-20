"""Turning a shape into a *named* table class.

Every table this module owns exists once per table set (Phase 5 §6): once for
the global set and once more for each declared collection. The columns are
written exactly once, in an ordinary ``class`` body inside the factory, and
this module is what stamps that body out under a distinct class name and
table name.

**Why the class name has to differ.** SQLAlchemy's declarative registry is
keyed by ``(class name, module name)``; two ``IndexText`` classes on one
``Base`` collide there and the second replaces the first in the string-lookup
table, with a ``SAWarning`` saying so. Nothing here resolves a relationship by
string — there is no ``Relationship`` in this module at all — so the collision
would be harmless *today*, which is exactly the kind of harmless that stops
being harmless quietly. A ``class`` statement cannot take a computed name, so
the concrete subclass is built with :func:`types.new_class` instead and the
readable half stays a ``class`` body one line above it.
"""

from __future__ import annotations

import types
from typing import Any


def table_class(
    name: str,
    bases: tuple[type, ...],
    *,
    tablename: str,
    table_args: tuple[Any, ...] | None = None,
    doc: str | None = None,
) -> Any:
    """A ``table=True`` SQLModel class named ``name`` mapped to ``tablename``.

    ``bases`` is ``(Base, <the shape>)`` — the module's declarative base and
    the plain ``SQLModel`` subclass holding the column declarations. The shape
    carries no ``table=True``, so it never reaches the declarative registry
    and only the class built here is a mapper.
    """
    namespace: dict[str, Any] = {
        # The factory's own module, so a traceback and a ``repr`` point at the
        # file the columns are actually written in.
        "__module__": bases[-1].__module__,
        "__qualname__": name,
        "__tablename__": tablename,
    }
    if doc is not None:
        namespace["__doc__"] = doc
    if table_args is not None:
        namespace["__table_args__"] = table_args
    return types.new_class(name, bases, {"table": True}, lambda ns: ns.update(namespace))
