"""No deep frontend import into another module's package (#337)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_ts_imports

MAIN = {"main": "./pagebuilder/index.ts"}
EXPORTS = {"exports": {".": "./a/index.ts", "./w.css": "./a/w.css"}}


def _repo(tmp_path: Path) -> Path:
    for module, pkg, entry in (
        ("pagebuilder", "pagebuilder", MAIN),
        ("analytics", "a", EXPORTS),
        ("news", "news", {}),
    ):
        d = tmp_path / "modules" / module / pkg
        d.mkdir(parents=True)
        manifest = {"name": f"@simple-module-py/{module}", **entry}
        (d.parent / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "host" / "client_app").mkdir(parents=True)
    return tmp_path


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _errors(root: Path) -> str:
    return "\n".join(check_ts_imports.check(root))


def test_the_repo_has_no_deep_imports():
    assert check_ts_imports.check() == []


def test_a_package_root_passes_through_main_or_exports(tmp_path):
    root = _repo(tmp_path)
    _write(root, "modules/news/news/a.ts", "import { x } from '@simple-module-py/pagebuilder';\n")
    _write(root, "host/client_app/a.ts", "import { y } from '@simple-module-py/analytics';\n")
    _write(
        root, "modules/news/news/b.ts", "import { Button } from '@simple-module-py/ui/button';\n"
    )
    assert _errors(root) == ""


def test_a_deep_package_import_is_refused_in_every_form(tmp_path):
    root = _repo(tmp_path)
    deep = "@simple-module-py/pagebuilder/pagebuilder/ui/fields"
    _write(
        root,
        "modules/news/news/a.tsx",
        f"import {{\n  a,\n}} from '{deep}';\n"
        f"export * from '{deep}';\n"
        f"await import('{deep}');\n"
        f"vi.mock('{deep}', () => ({{}}));\n",
    )
    lines = _errors(root).splitlines()
    assert [line.split(":")[1] for line in lines] == ["3", "4", "5", "6"]
    assert all("deep import into @simple-module-py/pagebuilder" in line for line in lines)


def test_a_css_deep_import_is_refused(tmp_path):
    root = _repo(tmp_path)
    _write(
        root,
        "host/client_app/s.css",
        '@import "@simple-module-py/pagebuilder/pagebuilder/static/w.css";\n',
    )
    assert "host/client_app/s.css:1: deep import" in _errors(root)


def test_a_subpath_exports_declares_is_still_refused(tmp_path):
    root = _repo(tmp_path)
    _write(root, "host/client_app/s.css", '@import "@simple-module-py/analytics/w.css";\n')
    assert "host/client_app/s.css:1: deep import into @simple-module-py/analytics" in _errors(root)


def test_the_host_stylesheet_is_the_one_allowance():
    (entry,) = check_ts_imports.ALLOWLIST
    assert entry == (
        "host/client_app/styles.css",
        "@simple-module-py/pagebuilder/pagebuilder/static/widgets-base.css",
    )


def test_a_module_without_an_entry_cannot_be_imported(tmp_path):
    root = _repo(tmp_path)
    _write(root, "modules/pagebuilder/pagebuilder/a.ts", "import '@simple-module-py/news';\n")
    assert "@simple-module-py/news has no '.' export or main" in _errors(root)


def test_a_relative_path_into_another_module_is_refused(tmp_path):
    root = _repo(tmp_path)
    _write(
        root,
        "modules/news/news/ui/a.ts",
        "import { x } from '../../../pagebuilder/pagebuilder/ui/fields';\n"
        "import { y } from '../b';\n",
    )
    _write(root, "host/client_app/a.ts", "import '../../modules/news/news';\n")
    errors = _errors(root)
    assert "modules/news/news/ui/a.ts:1: relative import into modules/pagebuilder/" in errors
    assert "host/client_app/a.ts:1: relative import into modules/news/" in errors
    assert len(errors.splitlines()) == 2


def test_comments_and_globs_are_not_imports(tmp_path):
    root = _repo(tmp_path)
    _write(
        root,
        "modules/pagebuilder/pagebuilder/puck-blocks.ts",
        "// import { x } from '@simple-module-py/news/news/a';\n"
        "/* from '../../news/news/a' */\n"
        "import.meta.glob('../../*/*/pagebuilder-blocks.ts', { eager: true });\n",
    )
    assert _errors(root) == ""


def test_the_allowlist_exempts_one_file_and_specifier(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    deep = "@simple-module-py/pagebuilder/pagebuilder/x"
    _write(root, "modules/news/news/a.ts", f"import '{deep}';\n")
    monkeypatch.setitem(check_ts_imports.ALLOWLIST, ("modules/news/news/a.ts", deep), "test")
    assert _errors(root) == ""


def test_import_text_inside_a_string_is_not_an_import(tmp_path):
    root = _repo(tmp_path)
    deep = "@simple-module-py/pagebuilder/pagebuilder/ui/fields"
    _write(
        root,
        "modules/news/news/a.ts",
        f"const sample = \"import {{ x }} from '{deep}';\";\n"
        f"const doc = `\nimport('{deep}');\nvi.mock('{deep}');\n`;\n"
        f"const one = 'from \"{deep}\"';\n",
    )
    assert _errors(root) == ""


def test_a_static_template_specifier_counts_and_a_computed_one_does_not(tmp_path):
    root = _repo(tmp_path)
    deep = "@simple-module-py/pagebuilder/pagebuilder/ui/fields"
    _write(
        root,
        "modules/news/news/a.ts",
        f"await import(`{deep}`);\n"
        f"vi.mock(`{deep}`, () => ({{}}));\n"
        "await import(`@simple-module-py/pagebuilder/${name}`);\n",
    )
    lines = _errors(root).splitlines()
    assert [line.split(":")[1] for line in lines] == ["1", "2"]


def test_an_unquoted_css_url_import_is_checked(tmp_path):
    root = _repo(tmp_path)
    _write(
        root,
        "host/client_app/s.css",
        "@import url(@simple-module-py/pagebuilder/internal.css);\n"
        '@import url( "@simple-module-py/pagebuilder/other.css" );\n',
    )
    lines = _errors(root).splitlines()
    assert [line.split(":")[1] for line in lines] == ["1", "2"]
    assert all("deep import into @simple-module-py/pagebuilder" in line for line in lines)
