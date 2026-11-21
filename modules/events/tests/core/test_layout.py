"""Events knows no sibling module: they depend on events (through its contracts), never back."""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "sm_events"
SIBLINGS = "sm_records|sm_images|sm_newsletter|sm_billing|sm_ai|news|pagebuilder"
IMPORT = re.compile(rf"^\s*(from|import)\s+({SIBLINGS})\b", re.MULTILINE)
DYNAMIC = re.compile(rf"""(import_module|find_spec)\(\s*f?["']({SIBLINGS})\b""")
TS = re.compile(
    r"""['"]@simple-module-py/(records|images|news|newsletter|billing|ai|pagebuilder)\b"""
)
ALLOWED = {"integrations/pagebuilder.py"}  # PR 4's guarded optional integration
# PR 7: the blocks. These (and only these) may import pagebuilder's package entry, and nothing
# else of a sibling's; ``ui/blocks/boundary.test.ts`` pins the same rule from the TS side.
BLOCKS_MAY_IMPORT_PAGEBUILDER = (
    "pagebuilder-blocks.ts",
    "ui/page-tests/pagebuilder-blocks.test.ts",
)
BLOCKS_DIR = "ui/blocks/"
PAGEBUILDER_ENTRY = re.compile(r"""['"]@simple-module-py/pagebuilder['"]""")


def _files(*suffixes: str):
    for path in sorted(PACKAGE.rglob("*")):
        if path.suffix in suffixes and "node_modules" not in path.parts:
            yield path, path.relative_to(PACKAGE).as_posix()


def test_no_sibling_imports():
    offenders = []
    for path, rel in _files(".py"):
        if rel in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        if IMPORT.search(text) or DYNAMIC.search(text):
            offenders.append(rel)
    assert offenders == []


def test_no_sibling_frontend_imports():
    offenders = []
    for path, rel in _files(".ts", ".tsx"):
        text = path.read_text(encoding="utf-8")
        if rel in BLOCKS_MAY_IMPORT_PAGEBUILDER or rel.startswith(BLOCKS_DIR):
            text = PAGEBUILDER_ENTRY.sub("", text)  # the one sibling import the blocks may make
        if TS.search(text):
            offenders.append(rel)
    assert offenders == []


def test_only_the_blocks_import_the_pagebuilder_entry():
    offenders = [
        rel
        for path, rel in _files(".ts", ".tsx")
        if PAGEBUILDER_ENTRY.search(path.read_text(encoding="utf-8"))
        and rel not in BLOCKS_MAY_IMPORT_PAGEBUILDER
        and not rel.startswith(BLOCKS_DIR)
    ]
    assert offenders == []
