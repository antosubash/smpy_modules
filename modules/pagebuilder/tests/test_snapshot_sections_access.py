"""A contributed section's own permissions gate its capture, download and restore (#80).

Driven with the fake ``notes`` section declaring permissions pagebuilder knows
nothing about, for a user holding all of pagebuilder's Import / Export but
none of them. Pages restore regardless.
"""

from __future__ import annotations

import pytest
from bundle_fake import NotesSection, notes, notes_client, seed_note, session
from page_helpers import create_draft
from pagebuilder.models import ContentSnapshot, SnapshotSource
from pagebuilder.permissions import PERM_APPROVE, PERM_EDIT, PERM_PUBLISH
from pagebuilder.snapshots.access import SYSTEM, SectionAccess
from pagebuilder.snapshots.registry import SectionRegistry
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_LIMITED = {
    "user_roles": ("limited",),
    "role_map": {"limited": [PERM_EDIT, PERM_PUBLISH, PERM_APPROVE]},
}


def _guarded() -> NotesSection:
    return NotesSection(
        capture_permissions=frozenset({"notes.view"}),
        apply_permissions=frozenset({"notes.view", "notes.write"}),
    )


def test_access_uses_the_framework_grant_rules():
    section = _guarded()
    assert SectionAccess(frozenset({"*"})).missing(section, "apply") == []
    assert SYSTEM.missing(section, "capture") == []
    assert SectionAccess(frozenset({"notes.view"})).missing(section, "apply") == ["notes.write"]
    assert SectionAccess(frozenset()).missing(NotesSection(), "apply") == []  # declares none


@pytest.mark.parametrize("bad", ["notes.view", [1], {""}, 7, None])
def test_permissions_must_be_a_set_of_names(bad):
    section = NotesSection()
    section.apply_permissions = bad
    with pytest.raises(ValueError, match="apply_permissions"):
        SectionRegistry().register(section)


async def _bundle_with_notes(tmp_path) -> bytes:
    """A bundle carrying the notes section, taken by an admin on another host."""
    data = b""
    async for source in notes_client(tmp_path / "source", _guarded()):
        await create_draft(source, slug="home", title="From the bundle")
        await seed_note(source, "welcome", {"text": "bundled"})
        taken = await source.post(_SNAPSHOTS, json={})
        data = (await source.get(f"{_SNAPSHOTS}/{taken.json()['id']}/download")).content
    return data


async def test_a_user_without_the_permissions_is_kept_out_of_the_section(tmp_path):
    data = await _bundle_with_notes(tmp_path)
    section = _guarded()
    async for client in notes_client(tmp_path / "target", section, **_LIMITED):
        await seed_note(client, "welcome", {"text": "live"})

        # Capture: left out, and the manifest says why.
        taken = (await client.post(_SNAPSHOTS, json={})).json()
        assert [e["section"] for e in taken["manifest"]["contents"]] == ["pagebuilder"]
        assert taken["manifest"]["omitted"][0]["permissions"] == ["notes.view"]
        assert ("capture", "default") not in section.calls

        # Download: a bundle carrying the section is a 403; one without it is not.
        uploaded = await client.post(f"{_SNAPSHOTS}/upload", files={"file": ("b.zip", data)})
        assert uploaded.status_code == 201, uploaded.text
        refused = await client.get(f"{_SNAPSHOTS}/{uploaded.json()['id']}/download")
        assert refused.status_code == 403
        assert refused.json()["detail"] == "Permission required: notes.view"
        assert (await client.get(f"{_SNAPSHOTS}/{taken['id']}/download")).status_code == 200

        # Restore: not planned, skipped at approval, pages restored.
        staged = await client.post(f"{_SNAPSHOTS}/{uploaded.json()['id']}/restore")
        plan = staged.json()["plan"]
        assert plan["sections"] == []
        assert plan["denied"] == [
            {
                "section": "notes",
                "label_key": "notes.bundle.title",
                "reason_key": "pagebuilder.plan.section_denied",
                "permissions": ["notes.view", "notes.write"],
            }
        ]
        applied = await client.post(f"/api/pagebuilder/imports/{staged.json()['id']}/approve")
        assert applied.status_code == 200, applied.text
        assert applied.json()["denied_sections"] == plan["denied"]
        assert await notes(client) == {"welcome": {"text": "live"}}
        pages = (await client.get("/api/pagebuilder/pages")).json()["items"]
        assert [p["title"] for p in pages] == ["From the bundle"]
        assert not [c for c in section.calls if c[0] in ("plan", "apply")]

        # The pre-restore snapshot is a system one: the section is in it.
        async with session(client) as db:
            result = await db.execute(
                select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
            )
            pre = result.scalar_one()
        assert "notes" in {e["section"] for e in pre.manifest["contents"]}
