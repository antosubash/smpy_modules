"""The real moved-path tables of ai, billing, news, pagebuilder and records (#319).

Each package's old paths are imported in a fresh interpreter by
``moved_paths_probe.py``: a warning only fires on the first import, and other
tests import these modules too. One process per package, not per path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

REPO = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("moved_paths_probe.py")
PACKAGES = {
    "ai": "sm_ai",
    "billing": "sm_billing",
    "news": "news",
    "pagebuilder": "pagebuilder",
    "records": "sm_records",
}
HOOKS = {name: REPO / f"modules/{mod}/{name}/core/moved_paths.py" for mod, name in PACKAGES.items()}


def _table(package: str) -> dict:
    return json.loads(HOOKS[package].with_suffix(".json").read_text(encoding="utf-8"))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], cwd=REPO, capture_output=True, text=True, check=False
    )


def _python(code: str, *flags: str) -> str:
    result = _run(*flags, "-c", code)
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.mark.parametrize("package", sorted(HOOKS))
def test_every_old_path_warns_and_is_the_new_module(package):
    """New paths import without a warning; each old one warns once and is the
    new module (or, for a split, carries the same objects); attributes lent by
    a path that is a real package again resolve; no real package attribute is
    overwritten by an old child."""
    assert _table(package).get("modules"), "the table is empty; run moved_paths.py --generate"
    result = _run(str(PROBE), package)
    assert result.returncode == 0, result.stderr[-3000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


@pytest.mark.parametrize(
    ("package", "attr"),
    [("news", "is_default"), ("pagebuilder", "is_default"), ("sm_records", "resolve_locale")],
)
def test_from_package_import_locales_is_the_real_module_again(package, attr):
    """``locales/`` is a data-only directory now, which Python would import as
    an empty namespace package; the alias must win."""
    code = f"from {package} import locales; print(locales.__name__, callable(locales.{attr}))"
    out = _python(code, "-W", "ignore::DeprecationWarning")
    assert out.split() == [f"{package}.core.locales", "True"]


def test_billing_teardown_subscribe_is_the_tenant_deleted_subscriber():
    """In 0.0.13 it subscribed to ``TenantDeleted``. A name match alone picked
    ``core.live.subscribe``, the settings-reload subscriber (#319 review)."""
    code = (
        "import sm_billing.teardown as old\n"
        "from sm_billing.subscriptions.deletion import tenant_deleted\n"
        "print(old.subscribe is tenant_deleted.subscribe)"
    )
    out = _python(code, "-W", "ignore::DeprecationWarning")
    assert out.strip() == "True"


@pytest.mark.parametrize(
    ("package", "name", "home"),
    [
        ("sm_billing.plans", "PlanService", "sm_billing.plans.service"),
        ("sm_ai.metering", "RequiresAiRequest", "sm_ai.metering.requests"),
    ],
)
def test_star_import_from_a_lending_package_reaches_its_old_names(package, name, home):
    """``import *`` never asks ``__getattr__`` for a name ``__all__`` omits."""
    code = (
        "import warnings\nwarnings.simplefilter('error', DeprecationWarning)\n"
        f"import {home} as h\nwarnings.simplefilter('always', DeprecationWarning)\n"
        "with warnings.catch_warnings(record=True) as seen:\n"
        f"    from {package} import *\n"
        f"print({name} is h.{name}, any('{package}.{name}' in str(w.message) for w in seen))"
    )
    out = _python(code)
    assert out.split() == ["True", "True"]


def test_the_hook_copies_are_identical():
    texts = {name: path.read_bytes() for name, path in HOOKS.items()}
    assert len(set(texts.values())) == 1, "core/moved_paths.py differs between packages"


def test_every_package_installs_its_hook():
    for name, hook in HOOKS.items():
        init = (hook.parent.parent / "__init__.py").read_text(encoding="utf-8")
        assert "install(__name__)" in init, name


def test_the_aliases_go_in_their_removal_release():
    """Two releases of warnings, then the aliases go (#319)."""
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for name in HOOKS:
        remove_in = _table(name)["remove_in"]
        assert Version(version["version"]) < Version(remove_in), (
            f"version {version['version']} reached remove_in {remove_in}: delete the 0.0.14 "
            "moved-path aliases (the TS/CSS stubs, core/moved_paths.*, the install() lines and "
            "the __getattr__/__path__ lines that name #319)"
        )
