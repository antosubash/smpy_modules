"""Pin the public paths the host, migration loader and CLI discover."""

import ast
import importlib
import importlib.metadata
import subprocess
import sys
from pathlib import Path

import sm_records
from sm_records.module import RecordsModule


def test_root_contains_only_discovery_paths():
    root = Path(sm_records.__file__).parent
    assert {p.name for p in root.glob("*.py")} == {
        "__init__.py",
        "module.py",
        "cli.py",
        "index.py",
        "collections.py",
        "seed.py",
    }
    for area in ("core", "web", "records"):
        tree = ast.parse((root / area / "__init__.py").read_text())
        assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)


def test_consumers_discover_package_resources():
    root = Path(sm_records.__file__).parent
    entry = next(
        ep for ep in importlib.metadata.entry_points(group="simple_module") if ep.name == "records"
    )
    assert entry.load() is RecordsModule
    assert importlib.import_module("sm_records.models").Record.__tablename__ == "records_record"
    assert RecordsModule().locale_dirs()["records"] == root / "locales"
    for path in (
        "locales/en.json",
        "locales/de.json",
        "pages/RecordEditor.tsx",
        "public_submissions/templates/confirm.txt",
    ):
        assert (root / path).is_file()
    assert root / "pagebuilder-blocks.ts" in root.parent.parent.glob("*/*/pagebuilder-blocks.ts")
    assert callable(importlib.import_module("sm_records.cli").main)
    public = importlib.import_module("sm_records.index")
    internal = importlib.import_module("sm_records.records.index")
    assert public.__all__ == internal.__all__
    assert all(getattr(public, name) is getattr(internal, name) for name in public.__all__)
    assert importlib.import_module("sm_records.contracts.schemas").RecordRead


def test_public_extension_lookups_keep_the_same_objects():
    for name in ("collections", "seed"):
        public = importlib.import_module(f"sm_records.{name}")
        internal = importlib.import_module(f"sm_records.records.{name}")
        assert public.__all__ == internal.__all__
        assert all(getattr(public, key) is getattr(internal, key) for key in public.__all__)


def test_newsletter_contract_imports_cleanly_first():
    """In a fresh interpreter, with nothing imported before it, the contract
    and the modules behind it load without an import cycle."""
    code = (
        "import sm_records.contracts.newsletter as n, "
        "sm_records.public_submissions.campaign_reads, "
        "sm_records.public_submissions.campaign_writes; "
        "assert n.MAX_SUBSCRIBER_BATCH == 1000"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_newsletter_admin_contract_imports_cleanly_first():
    """In a fresh interpreter, with nothing imported before it, the admin reads
    contract loads without an import cycle."""
    code = (
        "import sm_records.contracts.newsletter_admin as n; "
        "assert n.MAX_BROWSE_LIMIT == 100 and n.BROWSE_STATUSES[0] == 'pending'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
