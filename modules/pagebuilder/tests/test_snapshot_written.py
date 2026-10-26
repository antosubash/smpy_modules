"""``snapshots.written``: files follow the transaction that wrote them (#250).

The approve path calls ``discard`` itself when the apply raises; these cover
the rest — a rollback after the apply *returned* (a failed commit), a commit,
a savepoint, and that the cleanup stays inside the writing tenant's directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import MediaAsset
from pagebuilder.snapshots import written
from pagebuilder.snapshots.apply_media import restore_media
from pagebuilder.snapshots.blobs import BlobStore
from simple_module_db import tenant_context
from sqlmodel import select
from test_snapshot_apply_media import PNG, PNG_RED_2X2

pytestmark = pytest.mark.asyncio


def _index(blobs: BlobStore, *images: tuple[str, bytes]) -> dict:
    index = {}
    for name, data in images:
        digest = blobs.put(data)
        index[name] = {"sha256": digest, "original_filename": name, "content_type": "image/png"}
    return index


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


async def _restore(db, tmp_path, *images: tuple[str, bytes]) -> set[Path]:
    """Run the media step; return the files it wrote."""
    blobs = BlobStore(tmp_path / "blobs")
    root = resolve_media_root(db.settings.media_root)
    before = _files(root)
    await restore_media(db.session, db.settings, blobs, _index(blobs, *images))
    added = _files(root) - before
    assert added and set(written.tracked(db.session)) == added
    return added


async def test_a_rollback_after_the_apply_returned_removes_its_files(snapshot_db, tmp_path):
    """The failed-commit path: no raise inside approve, the session rolls back."""
    blobs_before = _files(tmp_path / "blobs")
    added = await _restore(snapshot_db, tmp_path, ("hero.png", PNG))

    await snapshot_db.session.rollback()

    assert not any(p.exists() for p in added)
    assert written.tracked(snapshot_db.session) == []
    # The content-addressed blob the bytes came from is shared, and stays.
    assert _files(tmp_path / "blobs") >= blobs_before
    assert len(_files(tmp_path / "blobs")) == 1


async def test_a_commit_keeps_the_files_and_a_later_rollback_does_not_touch_them(
    snapshot_db, tmp_path
):
    added = await _restore(snapshot_db, tmp_path, ("hero.png", PNG))

    await snapshot_db.session.commit()
    await snapshot_db.session.rollback()

    assert all(p.is_file() for p in added)
    rows = (await snapshot_db.session.execute(select(MediaAsset))).scalars().all()
    assert len(rows) == 1


async def test_a_savepoint_rollback_does_not_remove_the_outer_writes(snapshot_db, tmp_path):
    added = await _restore(snapshot_db, tmp_path, ("hero.png", PNG))

    nested = await snapshot_db.session.begin_nested()
    await nested.rollback()

    assert all(p.is_file() for p in added)
    await snapshot_db.session.rollback()
    assert not any(p.exists() for p in added)


async def test_a_file_that_existed_before_is_never_removed(snapshot_db, tmp_path):
    """An image the restore matched is reused, not rewritten, so not tracked."""
    session, settings = snapshot_db.session, snapshot_db.settings
    root = resolve_media_root(settings.media_root) / "default"
    root.mkdir(parents=True)
    (root / "existing.png").write_bytes(PNG)
    session.add(
        MediaAsset(
            filename="existing.png",
            original_filename="hero.png",
            content_type="image/png",
            size_bytes=len(PNG),
        )
    )
    await session.commit()

    added = await _restore(snapshot_db, tmp_path, ("hero.png", PNG), ("new.png", PNG_RED_2X2))
    assert root / "existing.png" not in added
    await session.rollback()

    assert (root / "existing.png").read_bytes() == PNG
    assert not any(p.exists() for p in added)


async def test_the_cleanup_stays_in_the_writing_tenants_directory(snapshot_db, tmp_path):
    media = resolve_media_root(snapshot_db.settings.media_root)
    other = media / "default"
    other.mkdir(parents=True)
    # Another tenant's file, named as one of this restore's could have been.
    (other / "neighbour.png").write_bytes(PNG)

    with tenant_context("acme"):
        added = await _restore(snapshot_db, tmp_path, ("hero.png", PNG))
        assert {p.parent for p in added} == {media / "acme"}
        await snapshot_db.session.rollback()

    assert not any(p.exists() for p in added)
    assert (other / "neighbour.png").read_bytes() == PNG
    assert json.dumps(sorted(p.name for p in _files(media))) == '["neighbour.png"]'
