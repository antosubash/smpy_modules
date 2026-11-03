"""Restoring media, where a bundle's filenames are not its keys.

Split out of ``test_snapshot_apply`` only to stay under the file-size cap; the
subject is the same ``apply_bundle``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pagebuilder.content.snapshots.apply import apply_bundle
from pagebuilder.content.snapshots.blobs import BlobStore
from pagebuilder.content.snapshots.capture import capture
from pagebuilder.media.media_files import resolve_media_root
from pagebuilder.models import Layout, MediaAsset, Page, PageRedirect
from sqlalchemy import delete
from sqlmodel import select

from tests.support.media_bytes import PNG, PNG_RED_2X2

pytestmark = pytest.mark.asyncio

async def _wipe(session):
    await session.execute(delete(PageRedirect))
    await session.execute(delete(Page))
    await session.execute(delete(MediaAsset))
    await session.execute(delete(Layout))
    await session.flush()


def _index(bundle: Path) -> dict:
    return json.loads((bundle / "media" / "index.json").read_text())


async def test_two_assets_sharing_a_filename_stay_two_files(snapshot_db, tmp_path):
    """``original_filename`` is a label, not a key.

    ``bundle_names`` disambiguates the collision as ``hero~2.png``, so a
    restore that deduplicated by name would resolve the second sentinel to the
    first image and never write its bytes — a silently wrong page, not a
    visible failure.
    """
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    root = resolve_media_root(settings.media_root) / "default"
    root.mkdir(parents=True, exist_ok=True)

    for name, data in (("uuid1.png", PNG), ("uuid2.png", PNG_RED_2X2)):
        (root / name).write_bytes(data)
        session.add(
            MediaAsset(
                filename=name,
                original_filename="hero.png",
                content_type="image/png",
                size_bytes=len(data),
            )
        )
    session.add(
        Page(
            slug="alpha",
            title="Alpha",
            draft_data={
                "content": [
                    {"props": {"id": "a", "src": "/media/pagebuilder/uuid1.png"}},
                    {"props": {"id": "b", "src": "/media/pagebuilder/uuid2.png"}},
                ]
            },
        )
    )
    await session.flush()

    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)
    await _wipe(session)

    result = await apply_bundle(session, settings, bundle, blobs, _index(bundle))
    assert result["media_added"] == 2

    assets = (await session.execute(select(MediaAsset))).scalars().all()
    assert len(assets) == 2
    # Both files came back, byte for byte, under distinct names.
    restored = {(root / a.filename).read_bytes() for a in assets}
    assert restored == {PNG, PNG_RED_2X2}

    alpha = (
        await session.execute(select(Page).where(Page.slug == "alpha"))
    ).scalars().one()
    blocks = alpha.draft_data["content"]
    assert blocks[0]["props"]["src"] != blocks[1]["props"]["src"]
    assert "asset://" not in json.dumps(alpha.draft_data)
