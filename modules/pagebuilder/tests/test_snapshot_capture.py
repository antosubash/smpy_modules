from __future__ import annotations

import json

import pytest
from pagebuilder.models import MediaAsset, Page, PageRedirect, PageStatus
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.capture import capture
from pagebuilder.snapshots.service import SnapshotService

pytestmark = pytest.mark.asyncio


async def _capture(snapshot_db, tmp_path, name="bundle"):
    dest = tmp_path / name
    blobs = BlobStore(tmp_path / "blobs")
    result = await capture(snapshot_db.session, snapshot_db.settings, dest, blobs)
    return dest, result


def _read(dest, *parts):
    return json.loads(dest.joinpath(*parts).read_text())


async def test_capture_writes_the_whole_bundle_tree(snapshot_db, tmp_path):
    dest, result = await _capture(snapshot_db, tmp_path)
    assert (dest / "manifest.json").is_file()
    assert (dest / "layout.json").is_file()
    assert (dest / "redirects.json").is_file()
    assert (dest / "media" / "index.json").is_file()
    manifest = _read(dest, "manifest.json")
    assert manifest["format_version"] == 2
    assert result.manifest == manifest
    assert result.size_bytes > 0


async def test_capture_skips_trashed_pages_but_keeps_templates(snapshot_db, tmp_path):
    from datetime import UTC, datetime

    session = snapshot_db.session
    session.add(Page(slug="live", title="Live"))
    session.add(Page(slug="starter", title="Starter", is_template=True))
    session.add(
        Page(slug="binned", title="Binned", deleted_at=datetime.now(UTC))
    )
    await session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    slugs = {entry["slug"] for entry in _read(dest, "manifest.json")["pages"]}
    assert slugs == {"live", "starter"}
    assert not (dest / "pages" / "binned.json").exists()


async def test_capture_records_the_parent_as_a_slug(snapshot_db, tmp_path):
    session = snapshot_db.session
    parent = Page(slug="parent", title="Parent")
    session.add(parent)
    await session.flush()
    session.add(Page(slug="child", title="Child", parent_id=parent.id))
    await session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    child = _read(dest, "pages", "child.json")
    assert child["parent_slug"] == "parent"
    assert "parent_id" not in child


async def test_capture_records_redirects_by_slug(snapshot_db, tmp_path):
    session = snapshot_db.session
    page = Page(slug="new-home", title="Home")
    session.add(page)
    await session.flush()
    session.add(PageRedirect(from_slug="old-home", page_id=page.id))
    await session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    assert _read(dest, "redirects.json") == [
        {"from_slug": "old-home", "locale": "en", "to_slug": "new-home"}
    ]


async def test_capture_rewrites_media_urls_to_sentinels(snapshot_db, tmp_path):
    from pagebuilder.media_files import resolve_media_root

    session = snapshot_db.session
    root = resolve_media_root(snapshot_db.settings.media_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "uuid1.jpg").write_bytes(b"image-bytes")
    session.add(
        MediaAsset(
            filename="uuid1.jpg",
            original_filename="hero.jpg",
            content_type="image/jpeg",
        )
    )
    session.add(
        Page(
            slug="home",
            title="Home",
            status=PageStatus.PUBLISHED,
            draft_data={
                "content": [{"props": {"src": "/media/pagebuilder/uuid1.jpg"}}]
            },
        )
    )
    await session.flush()

    dest, result = await _capture(snapshot_db, tmp_path)
    home = _read(dest, "pages", "home.json")
    assert home["draft_data"]["content"][0]["props"]["src"] == "asset://hero.jpg"
    index = _read(dest, "media", "index.json")
    assert index["hero.jpg"]["original_filename"] == "hero.jpg"
    assert BlobStore(tmp_path / "blobs").get(index["hero.jpg"]["sha256"]) == b"image-bytes"
    assert result.media[0]["bundle_name"] == "hero.jpg"


async def test_media_row_without_a_file_is_reported_not_fatal(snapshot_db, tmp_path):
    snapshot_db.session.add(
        MediaAsset(
            filename="gone.jpg",
            original_filename="gone.jpg",
            content_type="image/jpeg",
        )
    )
    await snapshot_db.session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    assert _read(dest, "manifest.json")["missing_media"] == ["gone.jpg"]


async def test_capture_replaces_a_stale_bundle_rather_than_merging(
    snapshot_db, tmp_path
):
    """A directory that already holds a bundle must not contribute to the new one.

    Snapshot ids come from the database while these files live on disk, so
    restoring a database backup without the filesystem hands the next snapshot
    a directory that already has pages in it. Merging would make the snapshot
    claim content the site never had — and the restore plan would offer to
    create it.
    """
    dest = tmp_path / "bundle"
    (dest / "pages").mkdir(parents=True)
    (dest / "pages" / "ghost.json").write_text('{"slug": "ghost"}')

    snapshot_db.session.add(Page(slug="real", title="Real"))
    await snapshot_db.session.flush()

    await _capture(snapshot_db, tmp_path, "bundle")

    assert not (dest / "pages" / "ghost.json").exists()
    assert {e["slug"] for e in _read(dest, "manifest.json")["pages"]} == {"real"}


async def test_two_captures_of_unchanged_content_are_byte_identical(
    snapshot_db, tmp_path
):
    snapshot_db.session.add(Page(slug="a", title="A"))
    await snapshot_db.session.flush()

    first, _ = await _capture(snapshot_db, tmp_path, "one")
    second, _ = await _capture(snapshot_db, tmp_path, "two")
    # created_at differs by design; every content document must not.
    for name in ("layout.json", "redirects.json", "pages/a.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


async def test_missing_media_is_not_rewritten_to_an_unresolvable_sentinel(
    snapshot_db, tmp_path
):
    """A row whose file is gone must leave the page's URL alone.

    Rewriting it to `asset://` produced a sentinel the bundle could not carry,
    and `from_sentinels` leaves an unresolvable one verbatim — so restoring
    wrote the literal string "asset://gone.jpg" into a live page as an image
    src. Leaving the URL keeps the reference exactly as broken as it was.
    """
    session = snapshot_db.session
    session.add(
        MediaAsset(
            filename="gone.jpg",
            original_filename="gone.jpg",
            content_type="image/jpeg",
        )
    )
    session.add(
        Page(
            slug="home",
            title="Home",
            draft_data={
                "content": [{"props": {"src": "/media/pagebuilder/gone.jpg"}}]
            },
        )
    )
    await session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    src = _read(dest, "pages", "home.json")["draft_data"]["content"][0]["props"]["src"]
    assert src == "/media/pagebuilder/gone.jpg"
    assert _read(dest, "manifest.json")["missing_media"] == ["gone.jpg"]


async def test_og_image_travels_as_a_sentinel(snapshot_db, tmp_path):
    """og_image is routinely a media URL, and a media URL is host-local.

    Carried verbatim it names the source host's UUID filename and 404s on
    every other host — a permanently broken social-share image that nothing
    reported, because it was never treated as an asset reference.
    """
    session = snapshot_db.session
    root = snapshot_db.settings.media_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "uuid1.jpg").write_bytes(b"image-bytes")
    session.add(
        MediaAsset(
            filename="uuid1.jpg",
            original_filename="hero.jpg",
            content_type="image/jpeg",
        )
    )
    session.add(
        Page(slug="home", title="Home", og_image="/media/pagebuilder/uuid1.jpg")
    )
    await session.flush()

    dest, _ = await _capture(snapshot_db, tmp_path)
    assert _read(dest, "pages", "home.json")["og_image"] == "asset://hero.jpg"


async def test_a_failed_capture_leaves_no_directory_behind(
    snapshot_db, tmp_path, monkeypatch
):
    """The row naming the directory rolls back; the files have to go too.

    Without the guard the bundle stayed on disk holding a copy of live
    content, drafts included, with no snapshot row left to reference or
    delete it — and on SQLite its id is reused, so the next snapshot would
    inherit it.
    """
    service = SnapshotService(snapshot_db.session, snapshot_db.settings)

    async def _boom(*args, **kwargs):
        # Half-written, the way a disk filling up mid-capture would leave it.
        dest = args[2]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "manifest.json").write_text("{}")
        raise OSError("No space left on device")

    monkeypatch.setattr("pagebuilder.snapshots.service.capture", _boom)
    with pytest.raises(OSError, match="No space left"):
        await service.take()
    assert not any(service.root.joinpath("snapshots").glob("*"))
