"""No published wheel may ship frontend test code.

Module test files sit beside the source they test, so a wheel built from
``packages`` picks them up. A host's Vite scans the installed module source,
meets ``import ... from 'vitest'``, cannot resolve it, and skips dependency
pre-bundling altogether (#63). Each module's ``[tool.hatch.build.targets.wheel]
exclude`` keeps them out; this builds every wheel and checks that it did, by
content rather than by name, so a new helper with a new name is caught too.

Skipped when ``uv`` is not on PATH.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# `from 'x'`, a bare side-effect `import 'x'`, and `require('x')`, with or
# without a subpath (`vitest/config`).
_TEST_IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*|\brequire\(\s*)['"]"""
    r"""(?:vitest|@testing-library/[^'"]+|happy-dom|jsdom)(?:/[^'"]*)?['"]"""
)
_FRONTEND_SOURCE = (".ts", ".tsx", ".js", ".jsx", ".mjs")


def _build(out: Path) -> list[Path]:
    subprocess.run(
        ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(out), "-q"],
        cwd=REPO,
        check=True,
    )
    built = sorted(out.glob("*.whl"))
    assert len(built) == len(list((REPO / "modules").glob("*/pyproject.toml")))
    return built


@pytest.fixture(scope="module")
def wheels(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """Every module's wheel, built once per run even under pytest-xdist.

    This file's tests may land on different xdist workers, and each would
    otherwise run its own full ``uv build`` of the workspace at the same time.
    Workers share their run's base temp directory, so the first one to take
    the lock builds into it and the rest reuse the result (the pattern
    pytest-xdist documents for session-wide fixtures).
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    if not os.environ.get("PYTEST_XDIST_WORKER"):  # serial, or xdist not even loaded
        return _build(tmp_path_factory.mktemp("wheels"))
    shared = tmp_path_factory.getbasetemp().parent / "wheels"
    with (shared.parent / "wheels.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (shared / "done").exists():
            return sorted(shared.glob("*.whl"))
        built = _build(shared)
        (shared / "done").touch()
        return built


def test_wheels_ship_no_frontend_test_code(wheels: list[Path]) -> None:
    offenders: list[str] = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if not name.endswith(_FRONTEND_SOURCE):
                    continue
                source = archive.read(name).decode("utf-8", errors="ignore")
                if ".test." in name or _TEST_IMPORT.search(source):
                    offenders.append(f"{wheel.name}: {name}")
    assert not offenders, "test code in wheels:\n" + "\n".join(offenders)


def _is_test_support(rel: Path) -> bool:
    """What every module's wheel ``exclude`` legitimately drops (#63)."""
    return (
        rel.name.endswith((".test.ts", ".test.tsx", "-test-support.ts", "-test-support.tsx"))
        or rel.name == "test-dom.tsx"
        or "__tests__" in rel.parts
        or "page-tests" in rel.parts
    )


def test_wheels_still_ship_frontend_source(wheels: list[Path]) -> None:
    # Guards the exclude list against a pattern broad enough to drop real
    # source: every non-test .ts/.tsx in a module's package must be in its wheel.
    missing: list[str] = []
    for module in sorted((REPO / "modules").glob("*/pyproject.toml")):
        root = module.parent
        wheel = next(w for w in wheels if w.name.startswith(f"simple_module_{root.name}-"))
        with zipfile.ZipFile(wheel) as archive:
            shipped = set(archive.namelist())
        for pkg in (d for d in root.iterdir() if (d / "__init__.py").is_file()):
            for src in pkg.rglob("*"):
                if src.suffix not in (".ts", ".tsx") or not src.is_file():
                    continue
                rel = src.relative_to(root)
                if "node_modules" in rel.parts or _is_test_support(rel):
                    continue
                if rel.as_posix() not in shipped:
                    missing.append(f"{wheel.name}: {rel}")
    assert not missing, "source dropped from wheels:\n" + "\n".join(missing)


def test_wheels_ship_the_moved_path_aliases(wheels: list[Path]) -> None:
    """The 0.0.14 aliases work only if each wheel ships its hook, its table and
    every stub the table names (#319)."""
    packages = 0
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            for table in (n for n in names if n.endswith("/core/moved_paths.json")):
                root = table.removesuffix("core/moved_paths.json")
                packages += 1
                assert f"{root}core/moved_paths.py" in names, wheel.name
                data = json.loads(archive.read(table))
                stubs = {**data.get("ts", {}), **data.get("css", {})}
                missing = sorted(rel for rel in stubs if f"{root}{rel}" not in names)
                assert not missing, f"{wheel.name} lacks stubs: {missing[:5]}"
    assert packages == 5, f"expected the five moved packages' tables, found {packages}"
