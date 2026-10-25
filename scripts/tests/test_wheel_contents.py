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


def test_wheels_still_ship_frontend_source(wheels: list[Path]) -> None:
    # Guards the exclude list against a pattern broad enough to drop real pages.
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            assert any(n.endswith(".tsx") for n in archive.namelist()), wheel.name
