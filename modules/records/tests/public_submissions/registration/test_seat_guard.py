"""A new way of deleting or trashing records cannot forget the seats (as ``forget_deliveries``)."""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[3] / "sm_records"
SERVICES = PACKAGE / "records"

DELETES = re.compile(r"sa_delete\(\s*(document|cls)\b|\.is_deleted\s*=\s*True|is_deleted=True")
HOOK = re.compile(r"seats\.on_(trashed|purged|type_purged)")


def test_every_record_delete_site_reaches_a_seat_hook():
    """Every statement that deletes a record document, and the one place that trashes one, lives in
    a module that calls a seat hook. A new delete path in another module fails here."""
    offenders = []
    for path in sorted(SERVICES.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if DELETES.search(text) and not HOOK.search(text):
            offenders.append(path.relative_to(PACKAGE).as_posix())
    assert offenders == [], f"{offenders} delete or trash records but never call a seat hook"


def test_the_restore_path_readmits():
    text = (SERVICES / "services" / "delete" / "_lifecycle.py").read_text(encoding="utf-8")
    assert "seats.on_restored" in text


def test_the_hooks_are_one_seam():
    text = (PACKAGE / "public_submissions" / "registration" / "seats.py").read_text("utf-8")
    for name in ("on_trashed", "on_restored", "on_purged", "on_type_purged"):
        assert f"async def {name}" in text
