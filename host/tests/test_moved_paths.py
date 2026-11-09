"""The 0.0.14 moved-path aliases (#319): the import hook, on a fake package.

Every module copies ``core/moved_paths.py`` byte for byte; the real tables are
exercised in ``test_moved_paths_tables.py``. Here a throwaway package carries
the pagebuilder copy and a small table, so each behaviour is checked in
isolation from the real move list.
"""

from __future__ import annotations

import importlib
import json
import pickle
import shutil
import sys
import warnings
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "modules/pagebuilder/pagebuilder/core/moved_paths.py"
PKG = "fakemoved"
TABLE = {
    "remove_in": "0.0.17",
    "modules": {
        f"{PKG}.old": f"{PKG}.new.thing",
        f"{PKG}.oldpkg": f"{PKG}.newpkg",
        f"{PKG}.split": [f"{PKG}.new.thing", f"{PKG}.new.other"],
        f"{PKG}.flat": [f"{PKG}.new.thing"],
    },
    "packages": {f"{PKG}.oldpkg": f"{PKG}.newpkg", f"{PKG}.flat": f"{PKG}.new"},
    "names": {f"{PKG}.split": ["A", "B"], f"{PKG}.flat": ["A"]},
    "attributes": {f"{PKG}.real": {"A": f"{PKG}.new.thing"}},
}
GETATTR = (
    "def __getattr__(name):\n"
    "    from ..core.moved_paths import moved_attribute\n\n"
    "    return moved_attribute(__name__, name)\n"
)
FILES = {
    "__init__.py": "from .core.moved_paths import install\n\ninstall(__name__)\n",
    "core/__init__.py": "",
    "core/moved_paths.json": json.dumps(TABLE),
    "new/__init__.py": "",
    "new/thing.py": "A = object()\nC = 3\n\n\nclass K:\n    pass\n",
    "new/other.py": "B = object()\n",
    "newpkg/__init__.py": "",
    "newpkg/sub.py": "X = 1\n",
    "real/__init__.py": GETATTR,
    "real/inner.py": "",
}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    root = tmp_path / PKG
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    shutil.copy(HOOK, root / "core/moved_paths.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    before = list(sys.meta_path)
    yield importlib.import_module(PKG)
    sys.meta_path[:] = before
    for name in [n for n in sys.modules if n == PKG or n.startswith(f"{PKG}.")]:
        del sys.modules[name]


def _finders():
    return [f for f in sys.meta_path if getattr(f, "moved_paths_package", None) == PKG]


def test_alias_is_the_new_module_and_warns_at_the_importer(fake):
    with pytest.warns(DeprecationWarning, match=rf"{PKG}\.old is deprecated.*0\.0\.17") as rec:
        import fakemoved.old  # noqa: F401 - the import statement is what is under test
    assert sys.modules[f"{PKG}.old"] is importlib.import_module(f"{PKG}.new.thing")
    assert [w.filename for w in rec] == [__file__]
    assert f"use {PKG}.new.thing" in str(rec[0].message)


def test_the_target_keeps_its_own_identity(fake):
    with pytest.warns(DeprecationWarning):
        old = importlib.import_module(f"{PKG}.old")
    thing = sys.modules[f"{PKG}.new.thing"]
    assert thing.__name__ == thing.__spec__.name == f"{PKG}.new.thing"
    assert thing.__spec__.loader is not _finders()[0]
    assert importlib.reload(thing) is thing
    assert sys.modules[f"{PKG}.old"] is thing
    copy = pickle.loads(pickle.dumps(old.K()))
    assert type(copy) is thing.K


def test_unlisted_submodule_of_an_old_package_maps_by_prefix(fake):
    with pytest.warns(DeprecationWarning):
        old = importlib.import_module(f"{PKG}.oldpkg.sub")
    assert old is importlib.import_module(f"{PKG}.newpkg.sub")
    assert sys.modules[f"{PKG}.oldpkg"] is sys.modules[f"{PKG}.newpkg"]


def test_split_module_carries_exactly_the_listed_names(fake):
    with pytest.warns(DeprecationWarning):
        split = importlib.import_module(f"{PKG}.split")
    thing = importlib.import_module(f"{PKG}.new.thing")
    other = importlib.import_module(f"{PKG}.new.other")
    assert split.A is thing.A
    assert split.B is other.B
    assert not hasattr(split, "C")


@pytest.mark.parametrize("parent_first", [True, False])
def test_old_package_whose_init_became_a_module_binds_its_children(fake, parent_first):
    with pytest.warns(DeprecationWarning):
        if parent_first:
            importlib.import_module(f"{PKG}.flat")
        sub = importlib.import_module(f"{PKG}.flat.other")
    flat = sys.modules[f"{PKG}.flat"]
    assert hasattr(flat, "__path__")
    assert flat.A is importlib.import_module(f"{PKG}.new.thing").A
    assert sub is importlib.import_module(f"{PKG}.new.other")
    assert flat.other is sub


def test_a_real_package_lends_its_lost_names_through_getattr(fake):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        real = importlib.import_module(f"{PKG}.real")  # the package itself never warns
        importlib.import_module(f"{PKG}.real.inner")
    with pytest.warns(DeprecationWarning, match=rf"{PKG}\.real\.A is deprecated") as rec:
        from fakemoved.real import A
    assert A is importlib.import_module(f"{PKG}.new.thing").A
    assert {w.filename for w in rec} == {__file__}
    with pytest.raises(AttributeError):
        real.Nope  # noqa: B018 - the attribute access is what is under test


def test_unknown_names_are_not_intercepted(fake):
    finder = _finders()[0]
    assert finder.find_spec(f"{PKG}.nope") is None
    assert finder.find_spec(f"{PKG}.real") is None
    assert finder.find_spec("json") is None
    assert finder.find_spec(f"{PKG}.oldpkg.missing") is None
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        importlib.import_module(f"{PKG}.new.thing")  # a new path never warns
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"{PKG}.nope")


def test_install_is_idempotent_and_first_in_line(fake):
    assert len(_finders()) == 1
    again = fake.core.moved_paths.install(PKG)
    assert _finders() == [again]
    assert sys.meta_path.index(again) == 0
