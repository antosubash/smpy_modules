"""A staged plan's contributed rows are served only from the host-side details (#80).

The serving boundary clears whatever items a stored plan holds, so a plan
that kept them inline can never leak them; details that cannot be read give
the counts with an explicit marker rather than silently empty lists.
"""

from __future__ import annotations

import logging

import pytest
from bundle_fake import NotesSection, notes_client, seed_note, session
from pagebuilder.models import PendingImport
from pagebuilder.snapshots.access import SectionAccess
from pagebuilder.snapshots.plan_views import IMPORTS_DIR, for_reader
from pagebuilder.snapshots.registry import SectionRegistry

pytestmark = pytest.mark.asyncio

_ITEM = {"title": "secret note", "slug": "secret", "locale": None, "note_key": None}
_PLAN = {
    "sections": [
        {
            "section": "notes",
            "label_key": "notes.bundle.title",
            "version": 1,
            "lines": [{"label_key": "notes.plan.new", "count": 1, "items": [_ITEM], "tone": None}],
            "overwrites": 0,
        }
    ]
}


def _registry() -> SectionRegistry:
    registry = SectionRegistry()
    registry.register(NotesSection(capture_permissions=frozenset({"notes.view"})))
    return registry


def _line(out: dict) -> dict:
    return out["sections"][0]["lines"][0]


def test_a_redacted_reader_never_gets_inline_items():
    out = for_reader(_PLAN, {"notes": [[_ITEM]]}, _registry(), SectionAccess(frozenset()))
    assert out["sections"][0]["redacted"] is True
    assert _line(out) == {**_PLAN["sections"][0]["lines"][0], "items": []}


def test_an_allowed_reader_gets_the_items_from_the_details_only():
    allowed = SectionAccess(frozenset({"notes.view"}))
    out = for_reader(_PLAN, {"notes": [[{"title": "from details"}]]}, _registry(), allowed)
    assert _line(out)["items"] == [{"title": "from details"}]
    assert "details_unavailable" not in out["sections"][0]


@pytest.mark.parametrize("details", [None, {}, {"notes": "nope"}, {"notes": [[], []]}])
def test_unreadable_details_give_counts_and_a_marker(details, caplog):
    allowed = SectionAccess(frozenset({"notes.view"}))
    with caplog.at_level(logging.WARNING, logger="pagebuilder.snapshots.plan_views"):
        out = for_reader(_PLAN, details, _registry(), allowed, import_id=7)

    entry = out["sections"][0]
    assert entry["details_unavailable"] is True
    assert entry["note_key"] == "pagebuilder.plan.section_details_unavailable"
    assert (_line(out)["count"], _line(out)["items"]) == (1, [])  # never the inline ones
    assert "import 7" in caplog.text


async def test_missing_details_on_disk_are_flagged_and_approval_stores_no_items(tmp_path):
    async for client in notes_client(tmp_path, NotesSection()):
        await seed_note(client, "welcome", {"text": "hi"})
        taken = await client.post("/api/pagebuilder/snapshots", json={})
        staged = await client.post(f"/api/pagebuilder/snapshots/{taken.json()['id']}/restore")
        import_id = staged.json()["id"]
        settings = client._transport.app.state.pagebuilder.settings  # type: ignore[attr-defined]
        details = settings.snapshot_root / IMPORTS_DIR / str(import_id) / "sections.json"
        assert details.is_file()
        details.unlink()

        pending = (await client.get("/api/pagebuilder/imports/pending")).json()
        assert pending["plan"]["sections"][0]["details_unavailable"] is True

        # Even a stored plan carrying items inline is audited without them.
        async with session(client) as db:
            row = await db.get(PendingImport, import_id)
            row.plan = {**row.plan, "sections": _PLAN["sections"]}
            await db.commit()
        assert (
            await client.post(f"/api/pagebuilder/imports/{import_id}/approve")
        ).status_code == 200
        async with session(client) as db:
            stored = (await db.get(PendingImport, import_id)).plan
        assert all(line["items"] == [] for e in stored["sections"] for line in e["lines"])
