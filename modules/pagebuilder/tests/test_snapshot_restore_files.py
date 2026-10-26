"""A failed restore removes the files it wrote, and only those (#250).

The approve request is one transaction, but the media files the apply uploads
are written to disk outside it. Driven through the real API with the fake
``notes`` section from ``bundle_fake``, whose ``fail_apply`` raises *after*
pagebuilder's media step has written its files.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from bundle_fake import NotesSection, notes_client, seed_note, session
from conftest import PNG_BYTES
from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import MediaAsset
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"


@pytest.fixture
def section() -> NotesSection:
    return NotesSection()


@pytest.fixture
async def client(tmp_path, section):
    async for c in notes_client(tmp_path, section):
        yield c


def _settings(client):
    return client._transport.app.state.pagebuilder.settings


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _media(client) -> set[Path]:
    return _files(resolve_media_root(_settings(client).media_root))


def _snapshot_files(client) -> set[Path]:
    return _files(Path(_settings(client).snapshot_root))


async def _upload(client, name: str, data: bytes = PNG_BYTES) -> dict:
    response = await client.post(
        "/api/pagebuilder/uploads", files={"file": (name, data, "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _asset_rows(client) -> list[MediaAsset]:
    async with session(client) as db:
        return list((await db.execute(select(MediaAsset))).scalars())


async def _staged_restore_of_a_deleted_image(client) -> tuple[int, dict]:
    """A snapshot holding two images, one deleted since: restoring re-uploads it.

    The other, *kept*, is still live, so the restore matches and reuses it —
    a file that existed before the restore and that no rollback may remove.
    """
    kept = await _upload(client, "kept.png")
    gone = await _upload(client, "gone.png")
    await seed_note(client, "welcome", {"image": gone["url"], "other": kept["url"]})
    snapshot = (await client.post(_SNAPSHOTS, json={})).json()
    deleted = await client.delete(f"/api/pagebuilder/uploads/{gone['id']}")
    assert deleted.status_code == 204, deleted.text
    staged = await client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    assert staged.status_code == 201, staged.text
    return staged.json()["id"], kept


async def _approve(client, import_id: int):
    return await client.post(f"/api/pagebuilder/imports/{import_id}/approve")


async def test_a_failing_section_leaves_no_new_media_file_or_row(client, section):
    import_id, kept = await _staged_restore_of_a_deleted_image(client)
    media_before, snapshots_before = _media(client), _snapshot_files(client)
    rows_before = {a.filename for a in await _asset_rows(client)}
    section.fail_apply = True

    with pytest.raises(RuntimeError, match="injected failure"):
        await _approve(client, import_id)

    # The re-uploaded image (and its thumbnails) are gone with their row; the
    # reused one, the bundle and its content-addressed blobs are all intact,
    # and the pre-restore snapshot's directory went with its row.
    assert _media(client) == media_before
    assert {a.filename for a in await _asset_rows(client)} == rows_before
    assert _snapshot_files(client) == snapshots_before
    assert any(p.name == kept["filename"] for p in media_before)


async def test_a_cancelled_approval_leaves_no_new_media_file_or_row(client, section):
    """CancelledError passes every ``except Exception`` on the way out."""
    import_id, _ = await _staged_restore_of_a_deleted_image(client)
    media_before, snapshots_before = _media(client), _snapshot_files(client)
    rows_before = {a.filename for a in await _asset_rows(client)}
    section.apply_error = asyncio.CancelledError()

    # Starlette's BaseHTTPMiddleware turns the cancelled call into its own
    # "No response returned." on the way out; either way, the request failed.
    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await _approve(client, import_id)

    assert _media(client) == media_before
    assert {a.filename for a in await _asset_rows(client)} == rows_before
    assert _snapshot_files(client) == snapshots_before


async def test_a_successful_restore_keeps_the_files_it_wrote(client):
    import_id, _ = await _staged_restore_of_a_deleted_image(client)
    media_before = _media(client)

    applied = await _approve(client, import_id)
    assert applied.status_code == 200, applied.text
    assert applied.json()["media_added"] == 1

    [restored] = [a for a in await _asset_rows(client) if a.original_filename == "gone.png"]
    names = {restored.filename} | {m["filename"] for m in (restored.variants or {}).values()}
    added = _media(client) - media_before
    assert {p.name for p in added} == names
    assert all(p.parent.name == restored.tenant_id for p in added)
    assert media_before <= _media(client)
