"""``scripts/moved_paths.py`` on a tiny fake repo and a fake rename list (#319).

No git tags are involved: ``generate`` takes the listing and a directory with
the old release's files, which is how ``--generate`` calls it too. The TS
surfaces come from the real TypeScript checker, so these tests need node.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import moved_paths

M = "modules/pb/pb"
TSCONFIG = {
    "compilerOptions": {
        "strict": True,
        "noEmit": True,
        "module": "esnext",
        "moduleResolution": "bundler",
        "jsx": "preserve",
        "paths": {"@/*": ["./pb/*"]},
    },
    "include": ["pb/**/*.ts", "pb/**/*.tsx"],
}
GETATTR = "def __getattr__(name):\n    return moved_attribute(__name__, name)\n"
OLD = {
    "service/__init__.py": "from ._a import A\n\n\nclass Svc:\n    pass\n",
    "service/_a.py": "A = 1\n",
    "index/__init__.py": "",
    "index/writer.py": "def write():\n    pass\n",
    "index/query.py": "def q():\n    pass\n\n\ndef gone():\n    pass\n",
    "locales.py": "def is_default():\n    pass\n",
    "metering.py": "def meter():\n    pass\n",
    "teardown.py": "def subscribe(bus):\n    bus.on('TenantDeleted', cancel_subscriptions)\n",
    "components/Hero.tsx": "export function Hero() {}\nexport default Hero;\n"
    "export type HeroProps = { a: number };\nexport function heroGone() {}\n",
    "components/x.css": ".x {}\n",
    "utils/api.ts": "export const getPage = 1;\nexport const listMedia = 2;\n"
    "export type Media = { id: string };\n",
    "fields/picker/gallery.tsx": "export class Gallery {}\n",
}
NEW = {
    "__init__.py": "",
    "core/__init__.py": "",
    "core/moved_paths.py": "",
    "content/__init__.py": "",
    "content/service/__init__.py": "",
    "content/service/pages.py": "class Svc:\n    pass\n",
    "content/service/_a.py": "A = 1\n",
    "records/__init__.py": "",
    "records/index/__init__.py": "",
    "records/index/writer.py": "def write():\n    pass\n",
    "records/index/query.py": "def q():\n    pass\n",
    "core/locales.py": "def is_default():\n    pass\n",
    "locales/en.json": "{}\n",
    "metering/__init__.py": (
        f"from ..core.moved_paths import moved_attribute\n\n__all__ = ['meter']\n\n\n{GETATTR}"
    ),
    "metering/requests.py": "def meter():\n    pass\n",
    # Two current `subscribe`s; the shorter path is the unrelated one.
    "core/live.py": "def subscribe(bus):\n    bus.on('SettingsReloaded', rebuild)\n",
    "subscriptions/__init__.py": "",
    "subscriptions/deletion/__init__.py": "",
    "subscriptions/deletion/tenant_deleted.py": (
        "def subscribe(bus):\n    bus.on('TenantDeleted', cancel_subscriptions)\n"
    ),
    "ui/components/Hero.tsx": "export function Hero() {}\nexport default Hero;\n",
    # A class, re-exported type-only: the stub must say `export type` too.
    "ui/components/hero-props.ts": "class Impl {}\nexport type { Impl as HeroProps };\n",
    "ui/components/x.css": ".x {}\n",
    "ui/utils/api.ts": "export const getPage = 1;\nexport type Media = { id: string };\n",
    "ui/utils/mediaApi.ts": "export const listMedia = 2;\n",
    "ui/fields/picker/gallery.tsx": "export class Gallery {}\n",
    "ui/fields/marker.ts": "export const marker = 1;\n",
}
LISTING = "\n".join(
    [
        f"R100\t{M}/service/__init__.py\t{M}/content/service/pages.py",
        f"R100\t{M}/service/_a.py\t{M}/content/service/_a.py",
        f"R100\t{M}/index/__init__.py\tmodules/other/tests/__init__.py",
        f"R100\t{M}/index/writer.py\t{M}/records/index/writer.py",
        f"D\t{M}/index/query.py",
        f"R090\t{M}/locales.py\t{M}/core/locales.py",
        f"D\t{M}/metering.py",
        f"D\t{M}/teardown.py",
        f"R080\t{M}/components/Hero.tsx\t{M}/ui/components/Hero.tsx",
        f"R100\t{M}/components/x.css\t{M}/ui/components/x.css",
        f"R081\t{M}/utils/api.ts\t{M}/ui/utils/api.ts",
        f"D\t{M}/fields/picker/gallery.tsx",
        f"R100\t{M}/fields/marker.ts\t{M}/ui/fields/marker.ts",
        f"R100\t{M}/tests/test_x.py\t{M}/tests/core/test_x.py",
        f"M\t{M}/module.py",
    ]
)
OLD["fields/marker.ts"] = "export const marker = 1;\n"


def _tree(base: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = base / M / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (base / "modules/pb/tsconfig.json").write_text(json.dumps(TSCONFIG), encoding="utf-8")
    (base / "modules/pb/package.json").write_text(
        '{"name": "@simple-module-py/pb"}', encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path):
    root, old = tmp_path / "repo", tmp_path / "old"
    _tree(root, NEW)
    _tree(old, OLD)
    tables = moved_paths.generate(root, LISTING, old)
    return root, tables[next(iter(tables))]


def _read(root: Path, rel: str) -> str:
    return (root / M / rel).read_text(encoding="utf-8")


def test_python_table(repo):
    _, table = repo
    modules = table["modules"]
    # An old package whose __init__ became a plain module is a compat package.
    assert modules["pb.service"] == ["pb.content.service.pages", "pb.content.service._a"]
    assert table["names"]["pb.service"] == ["A", "Svc"]
    assert table["packages"]["pb.service"] == "pb.content.service"
    assert modules["pb.service._a"] == "pb.content.service._a"
    # Git paired index/__init__.py with another package's test: its children decide.
    assert table["packages"]["pb.index"] == "pb.records.index"
    assert modules["pb.index.writer"] == "pb.records.index.writer"
    assert modules["pb.locales"] == "pb.core.locales"  # locales/ holds only data
    assert "pb.tests.test_x" not in modules


def test_deleted_module_keeps_what_survives_and_records_the_rest(repo):
    _, table = repo
    # Its parent pb.index is the real pb.records.index, whose own `query`
    # attribute the compat module would overwrite, so the parent is a compat
    # package too.
    assert table["modules"]["pb.index.query"] == ["pb.records.index.query"]
    assert table["names"]["pb.index.query"] == ["q"]
    assert table["removed"] == {"pb.index.query": ["gone"]}
    assert table["modules"]["pb.index"] == ["pb.records.index"]


def test_a_name_that_is_a_real_package_again_lends_through_getattr(repo):
    _, table = repo
    assert "pb.metering" not in table["modules"]
    assert table["attributes"] == {"pb.metering": {"meter": "pb.metering.requests"}}


def test_a_shared_name_goes_to_the_definition_like_the_old_one(repo):
    # Shortest-path alone picked core.live, the settings-reload subscriber,
    # for billing's old teardown.subscribe (#319 review).
    _, table = repo
    assert table["modules"]["pb.teardown"] == ["pb.subscriptions.deletion.tenant_deleted"]
    assert table["names"]["pb.teardown"] == ["subscribe"]


def test_ts_stubs(repo):
    root, table = repo
    assert _read(root, "components/Hero.tsx") == (
        "/** @deprecated Moved to `ui/components/Hero.tsx` in 0.0.14; "
        "this path goes in 0.0.17 (#319). */\n"
        "export * from '../ui/components/Hero';\n"
        "export { default } from '../ui/components/Hero';\n"
        "export type { HeroProps } from '../ui/components/hero-props';\n"
    )
    assert table["ts_removed"] == {"components/Hero.tsx": ["heroGone"]}
    assert _read(root, "utils/api.ts").endswith(
        "export * from '../ui/utils/api';\nexport { listMedia } from '../ui/utils/mediaApi';\n"
    )
    # Deleted, and its directory had no survivor to vote: the parent's move decides.
    assert table["ts"]["fields/picker/gallery.tsx"] == {"star": "ui/fields/picker/gallery.tsx"}
    assert _read(root, "components/x.css").endswith('@import "../ui/components/x.css";\n')


def test_check_passes_after_generate_and_generate_is_stable(repo):
    root, table = repo
    assert moved_paths.check(root) == []
    again = moved_paths.generate(root, LISTING, root.parent / "old")
    assert again[next(iter(again))] == table


def test_check_catches_a_hand_edited_stub(repo):
    root, _ = repo
    (root / M / "utils/api.ts").write_text("export * from '../ui/utils/api';\n", encoding="utf-8")
    assert any("utils/api.ts: not what --generate writes" in e for e in moved_paths.check(root))


def test_check_catches_a_package_that_stopped_lending(repo):
    root, _ = repo
    (root / M / "metering/__init__.py").write_text("", encoding="utf-8")
    assert any("pb.metering lends" in e for e in moved_paths.check(root))


def test_check_catches_a_lending_package_without_all(repo):
    # `import *` never asks __getattr__ for a name __all__ does not list.
    root, _ = repo
    (root / M / "metering/__init__.py").write_text(
        f"from ..core.moved_paths import moved_attribute\n\n\n{GETATTR}", encoding="utf-8"
    )
    assert any("list them in its __all__" in e for e in moved_paths.check(root))


@pytest.mark.parametrize(
    ("rel", "text", "needle"),
    [
        ("content/use.py", "from pb.service import Svc\n", "old path pb.service"),
        ("content/service/use.py", "from ...index import writer\n", "old path pb.index"),
        (
            "content/use2.py",
            "import pb.metering\nfrom pb.metering import meter\n",
            "pb.metering.meter",
        ),
        ("ui/use.ts", "import { getPage } from '../utils/api';\n", "old path ../utils/api"),
        ("ui/use2.tsx", "export { Gallery } from '@/fields/picker/gallery';\n", "@/fields"),
        ("ui/use3.ts", "const m = import('@simple-module-py/pb/components/Hero');\n", "Hero"),
    ],
)
def test_check_catches_an_internal_import_of_an_old_path(repo, rel, text, needle):
    root, _ = repo
    (root / M / rel).write_text(text, encoding="utf-8")
    errors = moved_paths.check(root)
    assert any(needle in e and rel in e for e in errors), errors


def test_new_paths_and_comments_are_not_old_imports(repo):
    root, _ = repo
    (root / M / "ui/ok.ts").write_text(
        "// import { x } from '../utils/api';\nimport { getPage } from './utils/api';\n",
        encoding="utf-8",
    )
    (root / M / "content/ok.py").write_text(
        "from pb.content.service import pages\n", encoding="utf-8"
    )
    assert moved_paths.check(root) == []


def test_old_import_after_a_multiline_comment_reports_its_own_line(repo):
    root, _ = repo
    (root / M / "ui/late.ts").write_text(
        "/*\n one\n two\n*/\nimport { getPage } from '../utils/api';\n", encoding="utf-8"
    )
    errors = moved_paths.check(root)
    assert any("ui/late.ts:5:" in e for e in errors), errors
