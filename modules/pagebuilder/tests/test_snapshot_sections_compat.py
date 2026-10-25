"""Contributed sections across hosts, bundle generations and tenants (#80).

The contract is only safe to ship if nothing that restored before still fails:
a bundle written before sections existed restores on a host that has one, a
bundle carrying a section restores on a host without it, and a section never
reads or writes another tenant's rows.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from bundle_fake import (
    FakeNote,
    NotesSection,
    notes,
    notes_client,
    prepare,
    rezip,
    seed_note,
    session,
)
from page_helpers import create_draft
from pagebuilder.contracts.bundle import register_section
from simple_module_db import tenant_context
from sqlmodel import select
from tenant_app import as_tenant, create_page, multi_client

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"


async def _bundle(client) -> tuple[dict, bytes]:
    taken = await client.post(_SNAPSHOTS, json={})
    assert taken.status_code == 201, taken.text
    snapshot = taken.json()
    data = (await client.get(f"{_SNAPSHOTS}/{snapshot['id']}/download")).content
    return snapshot, data


async def _upload(client, data: bytes, headers=None):
    return await client.post(
        f"{_SNAPSHOTS}/upload", files={"file": ("b.zip", data)}, headers=headers or {}
    )


async def _restore(client, snapshot_id: int, headers=None) -> dict:
    staged = await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore", headers=headers or {})
    assert staged.status_code == 201, staged.text
    applied = await client.post(
        f"/api/pagebuilder/imports/{staged.json()['id']}/approve", headers=headers or {}
    )
    assert applied.status_code == 200, applied.text
    return staged.json()["plan"]


async def test_a_host_without_the_section_restores_pages_and_keeps_the_rest(tmp_path):
    source_section = NotesSection()
    async for source in notes_client(tmp_path / "a", source_section):
        await create_draft(source, slug="home", title="Home")
        await seed_note(source, "welcome", {"text": "hi"})
        _, data = await _bundle(source)

    async for target in notes_client(tmp_path / "b", None):
        uploaded = await _upload(target, data)
        assert uploaded.status_code == 201, uploaded.text
        plan = await _restore(target, uploaded.json()["id"])
        assert plan["skipped"] == [{"section": "notes", "version": 1}]
        assert (plan["sections"], plan["absent"]) == ([], [])
        pages = (await target.get("/api/pagebuilder/pages")).json()["items"]
        assert [p["slug"] for p in pages] == ["home"]

        # Kept unread, so passing through this host loses nothing.
        again = await target.get(f"{_SNAPSHOTS}/{uploaded.json()['id']}/download")
        original = zipfile.ZipFile(io.BytesIO(data)).read("notes/notes.json")
        assert zipfile.ZipFile(io.BytesIO(again.content)).read("notes/notes.json") == original


async def test_a_required_section_this_host_lacks_is_refused(tmp_path):
    async for source in notes_client(tmp_path / "a", NotesSection()):
        snapshot, data = await _bundle(source)
    manifest = dict(snapshot["manifest"])
    manifest["contents"] = [
        {**e, "required": True} if e["section"] == "notes" else e for e in manifest["contents"]
    ]
    async for target in notes_client(tmp_path / "b", None):
        refused = await _upload(target, rezip(data, {"manifest.json": manifest}))
        assert refused.status_code == 422
        assert "requires the 'notes' section" in refused.json()["detail"]


@pytest.mark.parametrize("generation", ["minor-1", "unversioned-contents"])
async def test_a_bundle_from_before_sections_restores_and_leaves_notes_alone(tmp_path, generation):
    async for old_host in notes_client(tmp_path / "old", None):
        await create_draft(old_host, slug="home", title="Home")
        snapshot, data = await _bundle(old_host)
    manifest = dict(snapshot["manifest"])
    if generation == "minor-1":
        # Exactly what the previous build wrote: minor 1, no per-section counts.
        manifest["format_minor"] = 1
        manifest["contents"] = [
            {k: v for k, v in e.items() if k != "counts"} for e in manifest["contents"]
        ]
    else:
        # Before minor 1: no `contents` at all — read as pagebuilder alone.
        for key in ("format", "format_minor", "source", "tenant", "contents"):
            manifest.pop(key)
    old = rezip(data, {"manifest.json": manifest})

    section = NotesSection()
    async for host in notes_client(tmp_path / "new", section):
        await seed_note(host, "welcome", {"text": "live"})
        uploaded = await _upload(host, old)
        assert uploaded.status_code == 201, uploaded.text
        plan = await _restore(host, uploaded.json()["id"])
        assert plan["sections"] == [] and plan["skipped"] == []
        assert plan["absent"] == [{"section": "notes", "label_key": "notes.bundle.title"}]
        assert [c[0] for c in section.calls] == ["capture"]  # the pre-restore snapshot only
        assert await notes(host) == {"welcome": {"text": "live"}}
        pages = (await host.get("/api/pagebuilder/pages")).json()["items"]
        assert [p["slug"] for p in pages] == ["home"]


A, B = as_tenant("acme"), as_tenant("globex")


@pytest.mark.unbound_tenant
async def test_a_section_sees_only_the_bound_tenant(tmp_path):
    section = NotesSection()
    async for mt in multi_client(tmp_path):
        app = mt._transport.app  # type: ignore[attr-defined]
        assert register_section(app, section)
        await prepare(app)
        await create_page(mt, A, "home", "Home")
        for tenant, text in (("acme", "a"), ("globex", "b")):
            with tenant_context(tenant):
                await seed_note(mt, "welcome", {"text": text})

        taken = await mt.post(_SNAPSHOTS, json={}, headers=A)
        assert taken.status_code == 201, taken.text
        assert section.calls == [("capture", "acme")]
        root = app.state.pagebuilder.settings.snapshot_root / "snapshots"
        captured = json.loads((root / str(taken.json()["id"]) / "notes" / "notes.json").read_text())
        assert captured == [{"name": "welcome", "body": {"text": "a"}}]

        with tenant_context("globex"):
            async with session(mt) as db:
                row = (await db.execute(select(FakeNote))).scalar_one()
                row.body = {"text": "b2"}
                await db.commit()
        await _restore(mt, taken.json()["id"], headers=A)

        with tenant_context("acme"):
            assert await notes(mt) == {"welcome": {"text": "a"}}
        with tenant_context("globex"):
            assert await notes(mt) == {"welcome": {"text": "b2"}}
        assert {c[1] for c in section.calls if c[0] != "validate"} == {"acme"}
