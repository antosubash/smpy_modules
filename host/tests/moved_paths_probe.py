"""Import one package's old paths in a cold interpreter and report what went wrong (#319).

Run by ``test_moved_paths_tables.py`` as ``python moved_paths_probe.py <package>``,
one fresh process per package: a warning fires only on the first import, and an
earlier test may already have imported a module, so the checks need a process
of their own. Canonical modules are never unloaded (billing's SQLModel tables
would be defined twice). Prints a JSON list of problems; empty means all good.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import warnings
from pathlib import Path

PACKAGE = sys.argv[1]
problems: list[str] = []


def _new_modules(package: types.ModuleType) -> list[str]:
    base = Path(package.__file__).parent
    names = []
    for path in sorted(base.rglob("*.py")):
        parts = path.relative_to(base).with_suffix("").parts
        parts = parts[:-1] if parts[-1] == "__init__" else parts
        names.append(".".join([PACKAGE, *parts]))
    return names


with warnings.catch_warnings():
    warnings.simplefilter("error", DeprecationWarning)  # a new path never warns
    package = importlib.import_module(PACKAGE)
    new_modules = _new_modules(package)
    for name in new_modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            problems.append(f"new path {name}: {type(exc).__name__}: {exc}")

table = json.loads((Path(package.__file__).parent / "core/moved_paths.json").read_text())
seen: list[str] = []


def _record(rec: list[warnings.WarningMessage]) -> None:
    seen.extend(str(w.message) for w in rec if issubclass(w.category, DeprecationWarning))


for old, new in table.get("modules", {}).items():
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        try:
            alias = importlib.import_module(old)
        except Exception as exc:
            problems.append(f"{old}: {type(exc).__name__}: {exc}")
            continue
    _record(rec)
    if isinstance(new, str):
        if alias is not importlib.import_module(new):
            problems.append(f"{old} is not {new}")
        continue
    sources = [importlib.import_module(each) for each in new]
    for name in table.get("names", {}).get(old, []):
        expected = next((getattr(s, name) for s in sources if hasattr(s, name)), None)
        if getattr(alias, name, None) is not expected:
            problems.append(f"{old}.{name} is not the object from {new}")
    if old in table.get("packages", {}) and not hasattr(alias, "__path__"):
        problems.append(f"{old} is not importable as a package")

for module, attrs in table.get("attributes", {}).items():
    for attr, new in attrs.items():
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            value = getattr(importlib.import_module(module), attr, None)
        _record(rec)
        if value is None or value is not getattr(importlib.import_module(new), attr):
            problems.append(f"{module}.{attr} is not {new}.{attr}")

lent = table.get("attributes", {})
for old in [*table.get("modules", {}), *(f"{m}.{a}" for m, names in lent.items() for a in names)]:
    if not any(message.startswith(f"{old} is deprecated") for message in seen):
        problems.append(f"{old} imported without a DeprecationWarning")

# An old child sets an attribute on its parent's target: no real package may
# end up with a submodule attribute that is not that submodule.
for name in new_modules:
    module = sys.modules.get(name)
    for attr, value in vars(module or types.ModuleType("_")).items():
        real = sys.modules.get(f"{name}.{attr}")
        if isinstance(value, types.ModuleType) and real is not None and value is not real:
            problems.append(f"{name}.{attr} was overwritten by an old path")

print(json.dumps(problems))
