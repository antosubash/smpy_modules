"""Deprecated aliases for the import paths the 0.0.14 module layout moved (#319).

The package ``__init__`` calls :func:`install`, which puts one finder at the
front of ``sys.meta_path``. It answers only for the old names in
``moved_paths.json`` beside this file (written by ``scripts/moved_paths.py``):

- ``modules``: an old name and the module that replaced it. The old name then
  *is* that module object, after a ``DeprecationWarning`` naming the importer
  and the new path. A list instead (a file that was split or deleted, or an old
  package whose ``__init__`` became a plain module) gets a fresh module holding
  the names listed under ``names``, taken from the first list entry that has
  each one.
- ``packages``: every old package. Its alias is importable as a package, and
  when its children all moved under one new package, the value names that
  package, so an unlisted child maps by prefix.
- ``attributes``: an old module whose dotted name is a real package again
  today (``sm_ai.metering``). The finder never shadows it; the package's
  ``__getattr__`` calls :func:`moved_attribute` for the names it lost.

This file is byte-identical in every module (the copies cannot import one
another; ``host/tests/test_moved_paths_tables.py`` checks it). The aliases go in
the table's ``remove_in`` release, with this file and the ``install`` lines.
"""

from __future__ import annotations

import functools
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

from simple_module_core.deprecation import Deprecation

_TABLE = Path(__file__).with_name("moved_paths.json")


@functools.cache
def _table() -> dict:
    return json.loads(_TABLE.read_text(encoding="utf-8"))


def _warn(name: str, use: str, level: int) -> None:
    # The framework's message, but neither ``deprecated_module`` (on Python 3.12
    # its ``skip_file_prefixes`` is ignored and the warning would name this file)
    # nor its registry: ``remove_in`` there is a *framework* version, so a host's
    # expiry check would find every alias (0.0.17 < the framework's 0.0.4x)
    # overdue. ``level`` steps over our own frames; warnings steps over
    # importlib's frozen ones by itself, so the warning names the importer.
    Deprecation(name, remove_in=_table()["remove_in"], use=use).warn(stacklevel=level)


class MovedPathFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve the old names of one package to the modules that replaced them."""

    def __init__(self, package: str, table: dict) -> None:
        self.moved_paths_package = package
        self._prefix = f"{package}."
        self.modules: dict[str, str | list[str]] = table.get("modules", {})
        self.packages: dict[str, str | None] = table.get("packages", {})
        self.names: dict[str, list[str]] = table.get("names", {})

    def target(self, name: str) -> str | list[str] | None:
        """The new name (or names) behind ``name``, if it is an old one."""
        if not name.startswith(self._prefix):
            return None
        if name in self.modules:
            return self.modules[name]
        parts = name.split(".")
        for cut in range(len(parts) - 1, 1, -1):
            new_package = self.packages.get(".".join(parts[:cut]))
            if new_package:
                new = ".".join([new_package, *parts[cut:]])
                return new if importlib.util.find_spec(new) is not None else None
        return None

    def find_spec(self, fullname, path=None, target=None):
        if self.target(fullname) is None:
            return None
        return importlib.machinery.ModuleSpec(fullname, self, is_package=fullname in self.packages)

    def create_module(self, spec):
        return None  # a throwaway module: the target's own spec is never touched

    def exec_module(self, module: types.ModuleType) -> None:
        name = module.__name__
        new = self.target(name)
        if isinstance(new, str):
            replacement = importlib.import_module(new)
            _warn(name, new, level=3)
            sys.modules[name] = replacement  # what the import statement returns
            return
        sources = [importlib.import_module(each) for each in new or ()]
        names = self.names.get(name, ())
        for attr in names:
            source = next(s for s in sources if hasattr(s, attr))
            setattr(module, attr, getattr(source, attr))
        # A star import without ``__all__`` takes the public names, plus any child
        # already imported (``news.endpoints.api``), as in 0.0.13. Only a private
        # name the old ``__all__`` listed (``pagebuilder.service._UNSET``) needs
        # one; the table holds that ``__all__`` whenever the old module had it.
        if any(attr.startswith("_") for attr in names):
            module.__all__ = list(names)
        _warn(name, " / ".join(new or ()), level=3)


def moved_attribute(module: str, attr: str) -> object:
    """A name ``module`` exported in 0.0.13 that now lives elsewhere; warns once."""
    new = _table().get("attributes", {}).get(module, {}).get(attr)
    if new is None:
        raise AttributeError(f"module {module!r} has no attribute {attr!r}")
    value = getattr(importlib.import_module(new), attr)
    _warn(f"{module}.{attr}", f"{new}.{attr}", level=4)
    setattr(sys.modules[module], attr, value)
    return value


def install(package: str) -> MovedPathFinder:
    """Put this package's finder first in ``sys.meta_path``, once."""
    for finder in sys.meta_path:
        if getattr(finder, "moved_paths_package", None) == package:
            return finder
    finder = MovedPathFinder(package, _table())
    sys.meta_path.insert(0, finder)
    return finder
