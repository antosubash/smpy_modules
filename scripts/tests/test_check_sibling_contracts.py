"""A sibling floor must ship the contracts its dependant imports (#333)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_sibling_contracts as check

REPO = Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True,
    )


def _module(root: Path, name: str, package: str, deps: str = "", extras: str = "") -> Path:
    """A module whose package has an empty ``contracts``; *extras* is TOML under the table."""
    d = root / "modules" / name
    (d / package / "contracts").mkdir(parents=True, exist_ok=True)
    (d / package / "__init__.py").write_text("")
    (d / package / "contracts" / "__init__.py").write_text("")
    (d / "pyproject.toml").write_text(
        f'[project]\nname = "simple_module_{name}"\nversion = "0.0.2"\n'
        f"dependencies = [{deps}]\n"
        + (f"[project.optional-dependencies]\n{extras}\n" if extras else "")
        + f'[project.entry-points.simple_module]\n{name} = "{package}.module:M"\n'
    )
    return d / package


def _repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """`lists` 0.0.1 ships contracts.basic; `contracts.extra` and `added` come after."""
    root = tmp_path
    _git(root, "init", "-q")
    lists = _module(root, "lists", "sm_lists")
    (lists / "contracts" / "basic.py").write_text("def subscribers():\n    pass\n")
    mail = _module(root, "mail", "sm_mail", deps='"simple_module_lists>=0.0.1,<0.1"')
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "0.0.1")
    _git(root, "tag", "v0.0.1")
    return root, lists, mail


def _errors(root: Path) -> str:
    return "\n".join(check.check(root))


def test_an_import_the_floor_release_ships_passes(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text("from sm_lists.contracts.basic import subscribers\n")
    assert check.check(root) == []


def test_a_contract_module_newer_than_the_floor_fails(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "extra.py").write_text("X = 1\n")
    (mail / "use.py").write_text("from sm_lists.contracts.extra import X\n")
    (mail / "more.py").write_text("import sm_lists.contracts.extra\n")
    errors = _errors(root)
    assert "v0.0.1 does not ship sm_lists.contracts.extra" in errors
    assert "(and 1 more)" in errors


def test_a_name_added_to_a_shipped_module_fails(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "basic.py").write_text("def subscribers(): ...\ndef added(): ...\n")
    (mail / "use.py").write_text("from sm_lists.contracts.basic import added, subscribers\n")
    errors = check.check(root)
    assert len(errors) == 1
    assert "does not ship sm_lists.contracts.basic.added" in errors[0]


def test_a_submodule_imported_from_its_package_is_found(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text("from sm_lists.contracts import basic\n")
    assert check.check(root) == []


def test_an_import_module_string_counts_as_an_import(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text(
        'import importlib\n_C = "sm_lists.contracts.later"\nimportlib.import_module(_C)\n'
    )
    assert "does not ship sm_lists.contracts.later" in _errors(root)


def test_parent_package_and_exact_imports_count(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text("from sm_lists import contracts\nimport sm_lists.contracts\n")
    assert check.check(root) == []
    (mail / "use.py").write_text("from sm_lists import contracts\ncontracts.basic\n")
    assert check.check(root) == []


def test_parent_package_import_of_an_unshipped_contracts_fails(tmp_path):
    root, _, _ = _repo(tmp_path)
    late = _module(root, "late", "sm_late")
    (late / "contracts" / "__init__.py").unlink()
    (late / "contracts").rmdir()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "late without contracts")
    _git(root, "tag", "v0.0.2")
    (late / "contracts").mkdir()
    (late / "contracts" / "__init__.py").write_text("")
    user = _module(root, "user", "sm_user", deps='"simple_module_late>=0.0.2"')
    (user / "use.py").write_text("from sm_late import contracts\n")
    assert "v0.0.2 does not ship sm_late.contracts," in _errors(root)


def test_type_checking_names_are_not_exports(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "basic.py").write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from x import Model\n"
        "def subscribers(): ...\n"
    )
    _git(root, "commit", "-qam", "typed")
    _git(root, "tag", "-f", "v0.0.1")
    (mail / "use.py").write_text("from sm_lists.contracts.basic import Model\n")
    assert "does not ship sm_lists.contracts.basic.Model" in _errors(root)


def test_an_import_module_constant_from_another_file_counts(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "constants.py").write_text(
        'from typing import Final\nTARGET: Final = "sm_lists.contracts.later"\n'
    )
    (mail / "use.py").write_text(
        "import importlib\nfrom sm_mail import constants\n"
        "importlib.import_module(constants.TARGET)\n"
    )
    assert "does not ship sm_lists.contracts.later" in _errors(root)


def test_a_bare_name_resolves_to_its_own_files_constant(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "a.py").write_text(
        'import importlib\n_C = "sm_lists.contracts.basic"\nimportlib.import_module(_C)\n'
    )
    (mail / "b.py").write_text('_C = "sm_lists.contracts.removed"\n')
    assert check.check(root) == []


def test_a_type_only_import_is_not_checked(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        "    from sm_lists.contracts.later import X\n"
    )
    assert check.check(root) == []


def test_names_bound_in_a_top_level_loop_count(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "basic.py").write_text(
        "for KIND in ('a',):\n    LOOPED = KIND\ndef subscribers(): ...\n"
    )
    _git(root, "commit", "-qam", "loop")
    _git(root, "tag", "-f", "v0.0.1")
    (mail / "use.py").write_text("from sm_lists.contracts.basic import KIND, LOOPED\n")
    assert check.check(root) == []


def test_a_string_that_is_not_imported_is_ignored(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text('MESSAGE = "sm_lists.contracts.removed"\nprint(MESSAGE)\n')
    assert check.check(root) == []


def test_a_floor_above_the_newest_tag_is_checked_against_the_working_tree(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "extra.py").write_text("X = 1\n")
    (mail / "use.py").write_text("from sm_lists.contracts.extra import X\n")
    pyproject = mail.parent / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(">=0.0.1", ">=0.0.2"))
    assert check.check(root) == []
    (mail / "use.py").write_text("from sm_lists.contracts.extra import Y\n")
    assert "working tree does not ship sm_lists.contracts.extra.Y" in _errors(root)


def test_an_untagged_floor_below_the_newest_tag_names_no_release(tmp_path):
    root, _, mail = _repo(tmp_path)
    _git(root, "tag", "v0.0.3")
    pyproject = mail.parent / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(">=0.0.1", ">=0.0.2"))
    assert "no release v0.0.2 exists" in _errors(root)


def test_an_extras_floor_is_checked(tmp_path):
    root, _, _ = _repo(tmp_path)
    opt = _module(root, "opt", "sm_opt", extras='x = ["simple_module_lists>=0.0.1"]')
    (opt / "use.py").write_text("from sm_lists.contracts.later import X\n")
    assert "'simple_module_lists>=0.0.1': v0.0.1 does not ship" in _errors(root)


def test_tests_and_internals_are_not_checked(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "tests").mkdir()
    (mail / "tests" / "test_x.py").write_text("from sm_lists.contracts.later import X\n")
    (mail / "internal.py").write_text("from sm_lists.web import thing\n")
    assert check.check(root) == []


def test_no_tags_is_an_error_not_a_pass(tmp_path):
    _git(tmp_path, "init", "-q")
    _module(tmp_path, "lists", "sm_lists")
    assert "no v* release tags" in _errors(tmp_path)


def test_names_bound_by_unpacking_with_and_star_import_count(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "basic.py").write_text(
        "A, (B, *C) = 1, (2, 3)\ntry:\n    pass\nfinally:\n    D = 1\n"
        "with open(__file__):\n    E = 1\n"
        "def subscribers(): ...\n"
    )
    _git(root, "commit", "-qam", "unpacked")
    _git(root, "tag", "-f", "v0.0.1")
    (mail / "use.py").write_text("from sm_lists.contracts.basic import A, B, C, D, E\n")
    assert check.check(root) == []
    (lists / "contracts" / "basic.py").write_text("from .more import *\n")
    _git(root, "commit", "-qam", "star")
    _git(root, "tag", "-f", "v0.0.1")
    (mail / "use.py").write_text("from sm_lists.contracts.basic import Anything\n")
    assert check.check(root) == []


def test_a_floor_past_the_next_release_is_a_typo(tmp_path):
    root, _, mail = _repo(tmp_path)
    pyproject = mail.parent / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(">=0.0.1", ">=0.0.10"))
    assert "no release v0.0.10 exists" in _errors(root)
    current = ">=0.0.10"
    for next_release in ("0.0.2", "0.1.0", "1.0.0", "0.2.0"):  # next patch/minor/major, a typo
        pyproject.write_text(pyproject.read_text().replace(current, f">={next_release}"))
        current = f">={next_release}"
        errors = _errors(root)
        assert (f"no release v{next_release} exists" in errors) == (next_release == "0.2.0")


def test_a_prerelease_of_the_next_release_is_being_prepared(tmp_path):
    root, _, mail = _repo(tmp_path)
    pyproject = mail.parent / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(">=0.0.1", ">=0.0.2rc1"))
    assert check.check(root) == []
    _git(root, "tag", "v0.0.2rc1")
    pyproject.write_text(pyproject.read_text().replace(">=0.0.2rc1", ">=0.0.2"))
    assert check.check(root) == []


def test_a_hyphenated_prerelease_tag_is_read_by_its_own_name(tmp_path):
    root, lists, mail = _repo(tmp_path)
    (lists / "contracts" / "extra.py").write_text("X = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "rc")
    _git(root, "tag", "v0.0.2-rc1")
    (mail / "use.py").write_text("from sm_lists.contracts.extra import X\n")
    pyproject = mail.parent / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace(">=0.0.1", ">=0.0.2rc1"))
    assert check.check(root) == []


def test_a_type_only_import_module_is_not_checked(tmp_path):
    root, _, mail = _repo(tmp_path)
    (mail / "use.py").write_text(
        "import importlib\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        '    importlib.import_module("sm_lists.contracts.later")\n'
    )
    assert check.check(root) == []


def test_outside_a_clone_is_the_fetch_hint_not_a_traceback(tmp_path):
    assert "no v* release tags" in _errors(tmp_path)


def test_the_repo_passes():
    if not check._tags(REPO):
        pytest.skip("no release tags in this clone (a shallow checkout); CI's checks job has them")
    assert check.check(REPO) == []
