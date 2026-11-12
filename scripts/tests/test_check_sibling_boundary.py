"""A module reaches a sibling only through its ``contracts`` (#336)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_sibling_contracts as check

REPO = Path(__file__).resolve().parents[2]


def _module(root: Path, name: str, package: str) -> Path:
    d = root / "modules" / name
    (d / package / "contracts").mkdir(parents=True, exist_ok=True)
    (d / package / "__init__.py").write_text("")
    (d / package / "contracts" / "__init__.py").write_text("")
    (d / "pyproject.toml").write_text(
        f'[project]\nname = "simple_module_{name}"\nversion = "0.0.2"\ndependencies = []\n'
        f'[project.entry-points.simple_module]\n{name} = "{package}.module:M"\n'
    )
    return d / package


@pytest.fixture
def mail(tmp_path: Path) -> Path:
    _module(tmp_path, "lists", "sm_lists")
    return _module(tmp_path, "mail", "sm_mail")


def _errors(mail: Path, source: str, name: str = "use.py") -> list[str]:
    path = mail / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return check.check_boundary(mail.parents[2])


@pytest.mark.parametrize(
    "source",
    [
        "from sm_lists.contracts import basic\n",
        "from sm_lists.contracts.basic import subscribers\n",
        "import sm_lists.contracts.basic\n",
        "from sm_lists import contracts\n",
        "import sm_lists\n",
        "import importlib.util\nimportlib.util.find_spec('sm_lists')\n",
        "import importlib\nimportlib.import_module('sm_lists.contracts.basic')\n",
        "from sm_mail.web import own\n",  # its own internals
        "from fastapi import Depends\n",  # not a sibling
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from sm_lists.web import T\n",
    ],
)
def test_contracts_and_presence_checks_pass(mail, source):
    assert _errors(mail, source) == []


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("from sm_lists.web.deps import RequiresQuota\n", "sm_lists.web.deps"),
        ("import sm_lists.core.locales\n", "sm_lists.core.locales"),
        ("def f():\n    from sm_lists.core import locales\n", "sm_lists.core"),
        ("from sm_lists import contracts, settings\n", "sm_lists.settings"),
        ("import importlib\nimportlib.import_module('sm_lists.core.x')\n", "sm_lists.core.x"),
        (
            "from importlib.util import find_spec\nfind_spec('sm_lists.web.deps')\n",
            "sm_lists.web.deps",
        ),
        (
            "import importlib\nM = 'sm_lists.core.x'\nimportlib.import_module(M)\n",
            "sm_lists.core.x",
        ),
        ("from sm_lists.contracts_extra import X\n", "sm_lists.contracts_extra"),
    ],
)
def test_an_internal_of_a_sibling_fails(mail, source, target):
    errors = _errors(mail, source)
    assert len(errors) == 1
    assert f"modules/mail/sm_mail/use.py: imports {target}, which is not in" in errors[0]


def test_tests_are_not_checked(mail):
    assert _errors(mail, "from sm_lists.web import x\n", "tests/test_x.py") == []
    assert _errors(mail, "from sm_lists.web import x\n", "test_y.py") == []


def test_the_allowlist_names_one_import(mail):
    (mail / "use.py").write_text("from sm_lists.web import x\nfrom sm_lists.core import y\n")
    allowed = {("modules/mail/sm_mail/use.py", "sm_lists.web"): "a reason"}
    errors = check.check_boundary(mail.parents[2], allowed)
    assert len(errors) == 1
    assert "sm_lists.core" in errors[0]


def test_the_allowlist_is_empty():
    assert check.BOUNDARY_ALLOWLIST == {}


def test_the_repo_passes():
    assert check.check_boundary(REPO) == []
