"""A bundle's media is matched by the digest it is stored with (#356).

An upload is cleaned of its metadata, so a restored photo no longer hashes to
its bundle digest. Matching compares both, so restoring the same bundle twice
reuses the asset the first restore created instead of uploading a duplicate
and repointing the pages at it.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pagebuilder.content.snapshots.apply import apply_bundle
from pagebuilder.content.snapshots.blobs import BlobStore
from pagebuilder.content.snapshots.capture import capture
from pagebuilder.content.snapshots.media_match import match_existing
from pagebuilder.media.media_files import resolve_media_root
from pagebuilder.models import MediaAsset, Page
from PIL import Image
from sqlalchemy import delete, func, select

from tests.support.metadata_images import _exif

pytestmark = pytest.mark.asyncio


def _geotagged_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, format="JPEG", exif=_exif())
    return buf.getvalue()


async def _seed(session, settings) -> None:
    """A photo uploaded before #356: its file still carries GPS EXIF."""
    root = resolve_media_root(settings.media_root) / "default"
    root.mkdir(parents=True, exist_ok=True)
    data = _geotagged_jpeg()
    (root / "old.jpg").write_bytes(data)
    session.add(MediaAsset(filename="old.jpg", original_filename="photo.jpg",
                           content_type="image/jpeg", size_bytes=len(data)))
    session.add(Page(slug="story", title="Story", draft_data={
        "content": [{"type": "Image", "props": {"id": "i", "src": "/media/pagebuilder/old.jpg"}}]
    }))
    await session.flush()


def _index(bundle: Path) -> dict:
    return json.loads((bundle / "media" / "index.json").read_text())


async def _src(session) -> str:
    page = (await session.execute(select(Page).where(Page.slug == "story"))).scalars().one()
    return page.draft_data["content"][0]["props"]["src"]


async def test_restoring_a_metadata_bearing_bundle_twice_keeps_one_asset(snapshot_db, tmp_path):
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed(session, settings)
    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)
    await session.execute(delete(Page))
    await session.execute(delete(MediaAsset))
    await session.flush()

    first = await apply_bundle(session, settings, bundle, blobs, _index(bundle))
    assert first["media_added"] == 1
    url = await _src(session)
    [asset] = (await session.execute(select(MediaAsset))).scalars().all()
    stored = (resolve_media_root(settings.media_root) / "default" / asset.filename).read_bytes()
    assert b"SecretCam" not in stored  # cleaned on the way in

    second = await apply_bundle(session, settings, bundle, blobs, _index(bundle))
    assert second["media_added"] == 0
    assert await session.scalar(select(func.count()).select_from(MediaAsset)) == 1
    assert await _src(session) == url


async def test_without_the_blob_only_the_bundle_digest_matches(snapshot_db, tmp_path):
    """A store that lacks the blob cannot say how it would be stored: strict match."""
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed(session, settings)
    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)
    await session.execute(delete(MediaAsset))
    await session.flush()
    await apply_bundle(session, settings, bundle, blobs, _index(bundle))

    index = _index(bundle)
    assert set(await match_existing(session, settings, index, blobs)) == set(index)
    assert await match_existing(session, settings, index, BlobStore(tmp_path / "empty")) == {}
