"""A contributed bundle section rides every snapshot step (#80).

Driven through the real API with the fake ``notes`` section from
``bundle_fake``: captured into a snapshot, validated on upload, planned beside
the pages, applied after them in the approve request's own transaction — and
rolled back with them when it fails.
"""

from __future__ import annotations

import json

import pytest
from bundle_fake import FakeNote, NotesSection, notes, notes_client, rezip, seed_note, session
from conftest import PNG_BYTES
from page_helpers import create_draft
from pagebuilder.models import ContentSnapshot, ImportStatus, PendingImport, SnapshotSource
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PAGES = "/api/pagebuilder/pages"


@pytest.fixture
def section() -> NotesSection:
    return NotesSection()


@pytest.fixture
async def client(tmp_path, section):
    async for c in notes_client(tmp_path, section):
        yield c


async def _take(client) -> dict:
    response = await client.post(_SNAPSHOTS, json={})
    assert response.status_code == 201, response.text
    return response.json()


async def _stage(client, snapshot_id: int):
    return await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore")


async def _approve(client, import_id: int):
    return await client.post(f"/api/pagebuilder/imports/{import_id}/approve")


async def _upload_media(client) -> dict:
    response = await client.post(
        "/api/pagebuilder/uploads", files={"file": ("hero.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bundle_dir(client, snapshot_id: int):
    settings = client._transport.app.state.pagebuilder.settings
    return settings.snapshot_root / "snapshots" / str(snapshot_id)


async def test_capture_writes_the_section_and_its_manifest_entry(client, section):
    asset = await _upload_media(client)
    await seed_note(client, "welcome", {"image": asset["url"], "text": "hi"})

    snapshot = await _take(client)

    contents = {e["section"]: e for e in snapshot["manifest"]["contents"]}
    assert contents["notes"] == {
        "section": "notes",
        "version": 1,
        "required": False,
        "paths": ["notes/"],
        "counts": {"notes": 1},
    }
    assert contents["pagebuilder"]["counts"] == {"pages": 0, "redirects": 0, "media": 1}
    assert snapshot["manifest"]["format_minor"] == 2
    [doc] = json.loads((_bundle_dir(client, snapshot["id"]) / "notes" / "notes.json").read_text())
    # The media URL went through pagebuilder's own sentinel map.
    assert doc["body"] == {"image": "asset://hero.png", "text": "hi"}
    assert section.calls == [("capture", "default")]


async def test_plan_lists_the_section_and_apply_runs_after_pagebuilder(client, section):
    asset = await _upload_media(client)
    page = await create_draft(client, slug="home", title="Before")
    await seed_note(client, "welcome", {"image": asset["url"]})
    snapshot = await _take(client)
    await client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    await seed_note(client, "later", {"text": "kept"})

    staged = await _stage(client, snapshot["id"])
    assert staged.status_code == 201, staged.text
    plan = staged.json()["plan"]
    [entry] = plan["sections"]
    assert (entry["section"], entry["label_key"], entry["version"]) == (
        "notes",
        "notes.bundle.title",
        1,
    )
    # The sentinel resolves to this host's URL, so the note reads unchanged.
    assert [(line["label_key"], line["count"]) for line in entry["lines"]] == [
        ("notes.plan.new", 0),
        ("notes.plan.overwritten", 0),
    ]
    assert (plan["skipped"], plan["absent"]) == ([], [])

    applied = await _approve(client, staged.json()["id"])
    assert applied.status_code == 200, applied.text
    assert applied.json()["sections"] == {"notes": {"notes": 1}}
    assert (await notes(client))["welcome"] == {"image": asset["url"]}
    assert (await client.get(f"{_PAGES}/{page['id']}")).json()["title"] == "Before"
    assert [c[0] for c in section.calls if c[0] in ("plan", "apply")] == ["plan", "plan", "apply"]

    async with session(client) as db:
        audit = await db.get(PendingImport, staged.json()["id"])
    assert set(audit.plan["applied"]) == {"pagebuilder", "notes"}
    assert audit.plan["applied"]["notes"] == {"written": [{"name": "welcome"}]}


async def test_the_pre_restore_snapshot_carries_the_section(client):
    await seed_note(client, "welcome", {"text": "original"})
    snapshot = await _take(client)
    async with session(client) as db:
        row = (await db.execute(select(FakeNote))).scalar_one()
        row.body = {"text": "edited"}
        await db.commit()

    staged = await _stage(client, snapshot["id"])
    assert (await _approve(client, staged.json()["id"])).status_code == 200

    async with session(client) as db:
        result = await db.execute(
            select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
        )
        pre = result.scalar_one()
    sections = {e["section"]: e for e in pre.manifest["contents"]}
    assert sections["notes"]["counts"] == {"notes": 1}
    [doc] = json.loads((_bundle_dir(client, pre.id) / "notes" / "notes.json").read_text())
    assert doc["body"] == {"text": "edited"}  # the state the restore replaced
    assert (await notes(client)) == {"welcome": {"text": "original"}}


async def test_a_failing_section_rolls_back_pagebuilder_and_stays_pending(client, section):
    page = await create_draft(client, slug="home", title="Before")
    await seed_note(client, "welcome", {"text": "original"})
    snapshot = await _take(client)
    await client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    await client.put("/api/pagebuilder/layout", json={"header_data": {"content": [{"x": 1}]}})
    async with session(client) as db:
        row = (await db.execute(select(FakeNote))).scalar_one()
        row.body = {"text": "edited"}
        await db.commit()
    staged = await _stage(client, snapshot["id"])
    section.fail_apply = True

    # The fake flushes its write first, so the rollback has a note to undo too.
    with pytest.raises(RuntimeError, match="injected failure"):
        await _approve(client, staged.json()["id"])

    assert section.calls[-1][0] == "apply"
    assert (await client.get(f"{_PAGES}/{page['id']}")).json()["title"] == "After"
    layout = (await client.get("/api/pagebuilder/layout")).json()
    assert layout["header_data"] == {"content": [{"x": 1}]}
    assert (await notes(client)) == {"welcome": {"text": "edited"}}
    pending = (await client.get("/api/pagebuilder/imports/pending")).json()
    assert (pending["id"], pending["status"]) == (staged.json()["id"], ImportStatus.PENDING.value)
    async with session(client) as db:
        result = await db.execute(
            select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
        )
        assert result.scalars().all() == []
    root = _bundle_dir(client, 0).parent
    assert sorted(p.name for p in root.iterdir()) == [str(snapshot["id"])]


async def test_a_conflict_at_approval_writes_nothing(client, section):
    page = await create_draft(client, slug="home", title="Before")
    await seed_note(client, "welcome", {"text": "original"})
    snapshot = await _take(client)
    await client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    staged = await _stage(client, snapshot["id"])
    section.conflict_on = "welcome"  # the live rows moved between staging and approval

    refused = await _approve(client, staged.json()["id"])

    assert refused.status_code == 409
    assert "welcome" in refused.json()["detail"]
    assert (await client.get(f"{_PAGES}/{page['id']}")).json()["title"] == "After"
    assert (await client.get("/api/pagebuilder/imports/pending")).json()["id"] == staged.json()[
        "id"
    ]
    assert section.calls[-1][0] == "plan"  # never applied


async def test_a_conflict_at_staging_is_a_409(client, section):
    await seed_note(client, "welcome", {"text": "original"})
    snapshot = await _take(client)
    section.conflict_on = "welcome"
    assert (await _stage(client, snapshot["id"])).status_code == 409
    assert (await client.get("/api/pagebuilder/imports/pending")).json() is None


async def test_upload_validates_the_section(client, section):
    await seed_note(client, "welcome", {"text": "hi"})
    snapshot = await _take(client)
    data = (await client.get(f"{_SNAPSHOTS}/{snapshot['id']}/download")).content

    accepted = await client.post(_SNAPSHOTS + "/upload", files={"file": ("ok.zip", data)})
    assert accepted.status_code == 201, accepted.text
    assert ("validate", 1) in section.calls

    bad = rezip(data, {"notes/notes.json": {"not": "a list"}})
    refused = await client.post(_SNAPSHOTS + "/upload", files={"file": ("bad.zip", bad)})
    assert refused.status_code == 422
    assert "named notes" in refused.json()["detail"]
    missing = rezip(data, {"notes/notes.json": [{"name": "x", "body": "asset://gone.png"}]})
    refused = await client.post(_SNAPSHOTS + "/upload", files={"file": ("m.zip", missing)})
    assert refused.status_code == 422
    assert "gone.png" in refused.json()["detail"]
    # Neither rejected upload left a directory behind.
    root = _bundle_dir(client, 0).parent
    assert sorted(int(p.name) for p in root.iterdir()) == [snapshot["id"], accepted.json()["id"]]


async def test_an_unreadable_version_of_a_known_section_is_refused(client):
    snapshot = await _take(client)
    data = (await client.get(f"{_SNAPSHOTS}/{snapshot['id']}/download")).content
    manifest = dict(snapshot["manifest"])
    manifest["contents"] = [
        {**e, "version": 2} if e["section"] == "notes" else e for e in manifest["contents"]
    ]
    newer = rezip(data, {"manifest.json": manifest})
    refused = await client.post(_SNAPSHOTS + "/upload", files={"file": ("n.zip", newer)})
    assert refused.status_code == 422
    assert "unsupported version 2 of the 'notes' section" in refused.json()["detail"]
