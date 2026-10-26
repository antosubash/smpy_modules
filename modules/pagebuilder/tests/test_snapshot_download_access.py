"""Downloading a bundle fails closed on contributed sections (#80).

What a section needed is recorded on the snapshot row by this host when the
bundle is captured or uploaded, and enforced at download even once the
section is no longer registered. A section this host never knew has unknown
needs: only a holder of ``pagebuilder.approve`` may download it.
"""

from __future__ import annotations

import pytest
from bundle_fake import NotesSection, notes_client, rezip, seed_note
from pagebuilder.permissions import PERM_APPROVE, PERM_EDIT, PERM_PUBLISH
from pagebuilder.snapshots.access import DOWNLOAD_PERMISSIONS_KEY, SectionAccess
from pagebuilder.snapshots.plan_views import for_reader, split_items
from pagebuilder.snapshots.registry import SectionRegistry

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PUBLISHER = {"user_roles": ("pub",), "role_map": {"pub": [PERM_EDIT, PERM_PUBLISH]}}
_APPROVER = {
    "user_roles": ("appr",),
    "role_map": {"appr": [PERM_EDIT, PERM_PUBLISH, PERM_APPROVE]},
}


async def _notes_bundle(tmp_path) -> bytes:
    data = b""
    async for source in notes_client(tmp_path / "source", NotesSection()):
        await seed_note(source, "welcome", {"text": "a draft"})
        taken = await source.post(_SNAPSHOTS, json={})
        data = (await source.get(f"{_SNAPSHOTS}/{taken.json()['id']}/download")).content
    return data


async def _upload(client, data: bytes) -> dict:
    uploaded = await client.post(f"{_SNAPSHOTS}/upload", files={"file": ("b.zip", data)})
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()


@pytest.mark.parametrize(("who", "status"), [(_PUBLISHER, 403), (_APPROVER, 200)])
async def test_a_section_this_host_never_knew_needs_approve(tmp_path, who, status):
    data = await _notes_bundle(tmp_path)
    async for client in notes_client(tmp_path / "host", None, **who):
        uploaded = await _upload(client, data)
        assert uploaded["manifest"][DOWNLOAD_PERMISSIONS_KEY] == {"notes": None}

        response = await client.get(f"{_SNAPSHOTS}/{uploaded['id']}/download")

        assert response.status_code == status
        if status == 403:
            assert response.json()["detail"] == "Permission required: pagebuilder.approve"


async def test_a_forged_record_in_an_uploaded_manifest_is_ignored(tmp_path):
    data = await _notes_bundle(tmp_path)
    async for client in notes_client(tmp_path / "host", None, **_PUBLISHER):
        snapshot = await _upload(client, data)
        manifest = dict(snapshot["manifest"])
        manifest[DOWNLOAD_PERMISSIONS_KEY] = {"notes": []}
        forged = rezip(data, {"manifest.json": manifest})
        uploaded = await _upload(client, forged)

        assert uploaded["manifest"][DOWNLOAD_PERMISSIONS_KEY] == {"notes": None}
        response = await client.get(f"{_SNAPSHOTS}/{uploaded['id']}/download")
        assert response.status_code == 403


async def test_the_record_holds_after_the_section_is_unregistered(tmp_path):
    section = NotesSection(capture_permissions=frozenset({"notes.view"}))
    async for client in notes_client(tmp_path, section, **_APPROVER):
        app = client._transport.app  # type: ignore[attr-defined]
        # Uploaded while the section is registered: its needs are recorded.
        uploaded = await _upload(client, await _notes_bundle(tmp_path))
        assert uploaded["manifest"][DOWNLOAD_PERMISSIONS_KEY] == {"notes": ["notes.view"]}
        app.state.pagebuilder.bundle_sections._sections.pop("notes")  # module disabled

        response = await client.get(f"{_SNAPSHOTS}/{uploaded['id']}/download")

        # Holding approve does not stand in for a need this host recorded.
        assert response.status_code == 403
        assert response.json()["detail"] == "Permission required: notes.view"


def test_flat_applied_rows_from_before_sections_are_served_unchanged():
    plan = {"applied": {"created": [{"id": 1}], "overwritten": []}, "pages": {}}
    stored, details = split_items(plan)
    out = for_reader(stored, details, SectionRegistry(), SectionAccess(frozenset()))
    assert out["applied"] == plan["applied"]
