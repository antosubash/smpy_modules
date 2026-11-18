"""The write path's seam below the rights check is internal: only the importer calls it."""

from __future__ import annotations

from pathlib import Path

import sm_events
from sm_events.content import events_write

ROOT = Path(sm_events.__file__).parent
ALLOWED = {"content/events_write.py", "feeds/importing/write.py"}


def test_the_seam_is_not_part_of_the_public_surface():
    assert set(events_write.__all__) == {"create_event", "update_event"}
    assert not hasattr(events_write, "create_core") or events_write.create_core.__module__.endswith(
        "_core"
    )


def test_only_the_write_path_and_the_importer_import_it():
    importers = {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*.py")
        if "content._core" in p.read_text() or "content import _core" in p.read_text()
    }
    assert importers == ALLOWED, importers ^ ALLOWED
