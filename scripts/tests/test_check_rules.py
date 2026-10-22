"""CLAUDE.md's pin, pages/ and sibling-floor rules (#135)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_rules

REPO = Path(__file__).resolve().parents[2]
PAGE = "export default function Page() {\n  return null;\n}\n"


def _repo(tmp_path: Path, version: str = "0.0.11") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "root"\nversion = "{version}"\n', encoding="utf-8"
    )
    return tmp_path


def _module(root: Path, name: str, body: str = "", package: dict | None = None) -> Path:
    d = root / "modules" / name
    (d / name / "pages").mkdir(parents=True, exist_ok=True)
    (d / "pyproject.toml").write_text(
        f'[project]\nname = "simple_module_{name}"\nversion = "0.0.11"\n{body}', encoding="utf-8"
    )
    if package is not None:
        (d / "package.json").write_text(json.dumps(package), encoding="utf-8")
    return d


def _errors(root: Path) -> str:
    return "\n".join(check_rules.check(root))


# --- pins ---------------------------------------------------------------


def test_ranges_wildcards_and_third_party_pins_pass(tmp_path):
    """``==0.0.*`` is a prefix range; an exact pin on httpx is not this rule."""
    root = _repo(tmp_path)
    deps = '"simple_module_core>=0.0.35,<0.1", "simple_module_db==0.0.*", "httpx==0.27.0"'
    _module(root, "a", f"dependencies = [{deps}]\n")
    assert check_rules.check(root) == []


def test_exact_framework_pin_fails(tmp_path):
    root = _repo(tmp_path)
    _module(root, "a", 'dependencies = ["simple_module_core==0.0.36"]\n')
    assert "simple_module_core==0.0.36" in _errors(root)


def test_exact_pin_in_extra_or_dev_group_fails(tmp_path):
    root = _repo(tmp_path)
    _module(
        root,
        "a",
        '[project.optional-dependencies]\nx = ["simple_module_db===0.0.36"]\n'
        '[dependency-groups]\ndev = ["simple_module_test==0.0.36"]\n',
    )
    errors = _errors(root)
    assert "simple_module_db===0.0.36" in errors
    assert "simple_module_test==0.0.36" in errors


def test_pin_is_caught_under_any_spelling_of_the_name(tmp_path):
    for name in ("Simple_Module_Core", "simple-module-core", "simple.module.core"):
        root = _repo(tmp_path / name)
        _module(root, "a", f'dependencies = ["{name}==0.0.36"]\n')
        assert f"{name}==0.0.36" in _errors(root), name


def test_floor_equal_to_ceiling_is_an_exact_pin(tmp_path):
    root = _repo(tmp_path)
    _module(root, "a", 'dependencies = ["simple_module_core>=0.0.36,<=0.0.36"]\n')
    assert "pins exactly" in _errors(root)


def test_host_is_exempt(tmp_path):
    root = _repo(tmp_path)
    (root / "host").mkdir()
    (root / "host" / "pyproject.toml").write_text(
        '[project]\nname = "host"\ndependencies = ["simple_module_hosting==0.0.36"]\n',
        encoding="utf-8",
    )
    assert check_rules.check(root) == []


def test_exact_npm_pin_fails_and_ranges_pass(tmp_path):
    root = _repo(tmp_path)
    _module(
        root,
        "a",
        package={
            "peerDependencies": {"@simple-module-py/ui": "0.0.36", "react": "19.0.0"},
            "devDependencies": {"@simple-module-py/tsconfig": "*"},
            "dependencies": {"@simple-module-py/i18n": "=1.2.3", "@simple-module-py/x": "^1.2.3"},
        },
    )
    errors = check_rules.check(root)
    assert len(errors) == 2
    assert "@simple-module-py/ui" in errors[0] or "@simple-module-py/ui" in errors[1]
    assert "@simple-module-py/i18n" in "\n".join(errors)


def test_npm_workspace_and_alias_pins_fail(tmp_path):
    root = _repo(tmp_path)
    _module(
        root,
        "a",
        package={
            "dependencies": {
                "@simple-module-py/ui": "workspace:1.2.3",
                "ui-alias": "npm:@simple-module-py/ui@1.2.3",
                "@simple-module-py/i18n": "npm:@simple-module-py/i18n@= 1.2.3",
            },
        },
    )
    errors = _errors(root)
    assert "workspace:1.2.3" in errors
    assert "ui-alias" in errors
    assert "@= 1.2.3" in errors


def test_npm_ranges_pass(tmp_path):
    specs = [
        "1.2.3||2.0.0",
        "^1.2.3",
        "~1.2.3",
        ">=1.2.3 <2",
        "1.2.x",
        "1.2.3 - 1.4.0",
        "workspace:*",
        "workspace:^",
        "npm:@simple-module-py/ui@^1.2.3",
        "npm:react@19.0.0",
    ]
    root = _repo(tmp_path)
    deps = {f"@simple-module-py/p{i}": spec for i, spec in enumerate(specs)}
    _module(root, "a", package={"dependencies": deps})
    assert check_rules.check(root) == []


# --- pages/ -------------------------------------------------------------


def test_real_page_passes(tmp_path):
    root = _repo(tmp_path)
    d = _module(root, "a")
    (d / "a" / "pages" / "List.tsx").write_text(PAGE, encoding="utf-8")
    assert check_rules.check(root) == []


def test_page_without_default_export_fails(tmp_path):
    root = _repo(tmp_path)
    d = _module(root, "a")
    (d / "a" / "pages" / "helpers.tsx").write_text("export const x = 1;\n", encoding="utf-8")
    assert "a/pages/helpers.tsx: has no `export default`" in _errors(root)


def test_default_export_forms_pass(tmp_path):
    sources = {
        "Alias.tsx": "function Page() { return null; }\nexport { Page as default };\n",
        "Reexport.tsx": 'export { default } from "./Other";\n',
        "Both.tsx": 'export { default as default, x } from "./Other";\n',
    }
    root = _repo(tmp_path)
    pages = _module(root, "a") / "a" / "pages"
    for name, src in sources.items():
        (pages / name).write_text(src, encoding="utf-8")
    assert check_rules.check(root) == []


def test_default_export_in_a_comment_or_string_does_not_count(tmp_path):
    sources = {
        "Line.tsx": "// export default function Page() {}\nexport const x = 1;\n",
        "Block.tsx": "/*\n export default x;\n*/\nexport const x = 1;\n",
        "Str.tsx": 'export const s = "export default";\n',
        "Tpl.tsx": "export const s = `\nexport { x as default }`;\n",
        "Named.tsx": 'export { default as Page } from "./Other";\n',
    }
    root = _repo(tmp_path)
    pages = _module(root, "a") / "a" / "pages"
    for name, src in sources.items():
        (pages / name).write_text(src, encoding="utf-8")
    errors = _errors(root)
    for name in sources:
        assert f"a/pages/{name}: has no `export default`" in errors, name


def test_non_page_files_fail(tmp_path):
    root = _repo(tmp_path)
    pages = _module(root, "a") / "a" / "pages"
    (pages / "nested").mkdir()
    for name in ("List.test.tsx", "List.stories.tsx", "util.ts", ".gitkeep", "nested/x.ts"):
        (pages / name).write_text(PAGE, encoding="utf-8")
    errors = _errors(root)
    for name in ("List.test.tsx", "List.stories.tsx", "util.ts", ".gitkeep", "nested/x.ts"):
        assert f"a/pages/{name}: is not an Inertia page" in errors


def test_allowlisted_file_passes(tmp_path):
    root = _repo(tmp_path)
    pages = _module(root, "a") / "a" / "pages"
    (pages / "util.ts").write_text("", encoding="utf-8")
    assert check_rules.check_pages(root, frozenset({"modules/a/a/pages/util.ts"})) == []


# --- sibling floors -----------------------------------------------------


def _news(root: Path, extra: str) -> None:
    _module(root, "pagebuilder")
    _module(root, "news", f"[project.optional-dependencies]\n{extra}\n")


def test_sibling_floor_without_a_comment_fails(tmp_path):
    """news' pagebuilder extra at >=0.0.8 while the repo was at 0.0.11."""
    root = _repo(tmp_path)
    _news(root, 'pagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]')
    assert "needs a '# floor: <reason>' comment" in _errors(root)


def test_floor_is_not_compared_with_the_repo_version(tmp_path):
    """A lockstep release (bump_version.py leaves specifiers alone) must not fail lint."""
    extra = 'pagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]  # floor: labels'
    for version in ("0.0.11", "0.0.40", "0.1.0"):
        root = _repo(tmp_path / version, version)
        _news(root, extra)
        assert check_rules.check(root) == [], version


def test_sibling_is_matched_under_any_spelling(tmp_path):
    root = _repo(tmp_path)
    _news(root, 'pagebuilder = ["Simple-Module.Pagebuilder>=0.0.12,<0.1"]')
    assert "needs a '# floor: <reason>' comment" in _errors(root)


def test_floor_comment_inline_or_above_passes(tmp_path):
    inline = 'pagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]  # floor: only labels used'
    above = (
        "# Optional.\n# floor: 0.0.8 added localizeConfig\n"
        'pagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]'
    )
    for name, extra in (("inline", inline), ("above", above)):
        root = _repo(tmp_path / name)
        _news(root, extra)
        assert check_rules.check(root) == [], name


def test_floor_comment_separated_by_a_blank_line_does_not_count(tmp_path):
    root = _repo(tmp_path)
    _news(root, '# floor: stale\n\npagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]')
    assert "needs a '# floor: <reason>' comment" in _errors(root)


def test_floor_comment_above_a_mere_mention_does_not_count(tmp_path):
    root = _repo(tmp_path)
    _news(
        root,
        'pagebuilder = ["simple_module_pagebuilder>=0.0.8,<0.1"]\n\n'
        "# floor: about the note, not the requirement\n"
        'note = ["see simple_module_pagebuilder>=0.0.8,<0.1 above"]',
    )
    assert "needs a '# floor: <reason>' comment" in _errors(root)


def test_sibling_without_floor_fails(tmp_path):
    root = _repo(tmp_path)
    _news(root, 'pagebuilder = ["simple_module_pagebuilder<0.1"]')
    assert "has no >= floor" in _errors(root)


def test_framework_floor_is_not_a_sibling(tmp_path):
    root = _repo(tmp_path)
    _module(root, "a", 'dependencies = ["simple_module_core>=0.0.1,<0.1"]\n')
    assert check_rules.check(root) == []


# --- the real tree ------------------------------------------------------


def test_main_reports_violations(tmp_path, capsys):
    root = _repo(tmp_path)
    _module(root, "a", 'dependencies = ["simple_module_core==0.0.36"]\n')
    assert check_rules.main(["--root", str(root)]) == 1
    assert "FAIL: 1 rule violation" in capsys.readouterr().err


def test_repo_follows_the_rules():
    assert check_rules.check(REPO) == []
