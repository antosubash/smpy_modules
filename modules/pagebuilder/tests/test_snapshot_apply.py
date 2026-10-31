from __future__ import annotations

import json
from pathlib import Path

import pytest
from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import Layout, MediaAsset, Page, PageRedirect, PageStatus
from pagebuilder.snapshots.apply import apply_bundle
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.capture import capture
from sqlalchemy import delete
from sqlmodel import select

pytestmark = pytest.mark.asyncio

# A 1x1 PNG. Real bytes matter: MediaService sniffs content and rejects
# anything that is not actually an allowed image.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def _tree(root: Path) -> dict[str, object]:
    """Every document in a bundle, parsed, keyed by relative path.

    Parsed rather than raw so a mismatch names the document that differs
    instead of reporting "bytes differ" and leaving the reader to hunt.
    """
    out: dict[str, object] = {}
    for path in sorted(root.rglob("*.json")):
        payload = json.loads(path.read_text())
        if path.name == "manifest.json":
            # created_at is wall-clock by design; everything else must match.
            payload = {k: v for k, v in payload.items() if k != "created_at"}
        out[path.relative_to(root).as_posix()] = payload
    return out


async def _seed_rich_site(session, settings):
    """Pages with a parent, a redirect, media in content, and a layout."""
    root = resolve_media_root(settings.media_root) / "default"
    root.mkdir(parents=True, exist_ok=True)
    (root / "uuid1.png").write_bytes(PNG)
    session.add(
        MediaAsset(
            filename="uuid1.png",
            original_filename="hero.png",
            content_type="image/png",
            size_bytes=len(PNG),
        )
    )

    # "zeta" parents "alpha": the parent sorts *after* the child, so a
    # single-pass restore would fail to resolve it.
    zeta = Page(slug="zeta", title="Zeta")
    session.add(zeta)
    await session.flush()
    session.add(
        Page(
            slug="alpha",
            title="Alpha",
            parent_id=zeta.id,
            status=PageStatus.PUBLISHED,
            draft_data={
                "content": [{"props": {"id": "a", "src": "/media/pagebuilder/uuid1.png"}}]
            },
            published_data={"content": [{"props": {"id": "a"}}]},
        )
    )
    session.add(Page(slug="starter", title="Starter", is_template=True))
    await session.flush()
    session.add(PageRedirect(from_slug="old-alpha", page_id=zeta.id))
    session.add(
        Layout(
            header_data={"content": [{"props": {"src": "/media/pagebuilder/uuid1.png"}}]},
            footer_data={"content": [{"props": {"id": "f"}}]},
        )
    )
    await session.flush()


async def _wipe(session):
    await session.execute(delete(PageRedirect))
    await session.execute(delete(Page))
    await session.execute(delete(MediaAsset))
    await session.execute(delete(Layout))
    await session.flush()


def _index(bundle: Path) -> dict:
    return json.loads((bundle / "media" / "index.json").read_text())


async def test_round_trip_is_identical(snapshot_db, tmp_path):
    """capture -> wipe -> apply -> capture must reproduce the same bundle."""
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed_rich_site(session, settings)

    first = tmp_path / "one"
    await capture(session, settings, first, blobs)

    await _wipe(session)
    await apply_bundle(session, settings, first, blobs, _index(first))

    second = tmp_path / "two"
    await capture(session, settings, second, blobs)

    assert _tree(first) == _tree(second)


async def test_parent_resolves_even_when_it_sorts_after_the_child(
    snapshot_db, tmp_path
):
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed_rich_site(session, settings)
    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)
    await _wipe(session)

    await apply_bundle(session, settings, bundle, blobs, _index(bundle))

    result = await session.execute(select(Page).where(Page.slug == "alpha"))
    alpha = result.scalars().one()
    zeta = (await session.execute(select(Page).where(Page.slug == "zeta"))).scalars().one()
    assert alpha.parent_id == zeta.id


async def test_unresolvable_parent_becomes_none_rather_than_failing(
    snapshot_db, tmp_path
):
    session, settings = snapshot_db.session, snapshot_db.settings
    bundle = tmp_path / "b"
    (bundle / "pages").mkdir(parents=True)
    (bundle / "pages" / "orphan.json").write_text(
        json.dumps(
            {
                "slug": "orphan",
                "title": "Orphan",
                "status": "draft",
                "parent_slug": "nobody",
                "draft_data": {},
                "published_data": None,
            }
        )
    )
    (bundle / "redirects.json").write_text("[]")
    (bundle / "layout.json").write_text("{}")

    await apply_bundle(session, settings, bundle, BlobStore(tmp_path / "blobs"), {})

    page = (
        await session.execute(select(Page).where(Page.slug == "orphan"))
    ).scalars().one()
    assert page.parent_id is None


async def test_redirect_with_an_unresolvable_target_is_dropped(snapshot_db, tmp_path):
    session, settings = snapshot_db.session, snapshot_db.settings
    bundle = tmp_path / "b"
    (bundle / "pages").mkdir(parents=True)
    (bundle / "redirects.json").write_text(
        json.dumps([{"from_slug": "old", "to_slug": "nowhere"}])
    )
    (bundle / "layout.json").write_text("{}")

    result = await apply_bundle(
        session, settings, bundle, BlobStore(tmp_path / "blobs"), {}
    )
    assert result["redirects_dropped"] == ["old"]
    assert (await session.execute(select(PageRedirect))).scalars().all() == []


async def test_restoring_over_a_trashed_slug_revives_the_page(snapshot_db, tmp_path):
    from datetime import UTC, datetime

    session, settings = snapshot_db.session, snapshot_db.settings
    session.add(Page(slug="home", title="Binned", deleted_at=datetime.now(UTC)))
    await session.flush()

    bundle = tmp_path / "b"
    (bundle / "pages").mkdir(parents=True)
    (bundle / "pages" / "home.json").write_text(
        json.dumps(
            {
                "slug": "home",
                "title": "Home",
                "status": "draft",
                "parent_slug": None,
                "draft_data": {},
                "published_data": None,
            }
        )
    )
    (bundle / "redirects.json").write_text("[]")
    (bundle / "layout.json").write_text("{}")

    # A trashed page keeps its slug claimed; inserting a second would trip the
    # unique constraint, so the restore has to revive the existing row.
    await apply_bundle(session, settings, bundle, BlobStore(tmp_path / "blobs"), {})

    pages = (await session.execute(select(Page))).scalars().all()
    assert len(pages) == 1
    assert pages[0].title == "Home"
    assert pages[0].deleted_at is None


async def test_media_is_matched_by_original_filename_not_duplicated(
    snapshot_db, tmp_path
):
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed_rich_site(session, settings)
    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)

    # Apply onto the site it came from: the asset already exists, so nothing
    # is uploaded a second time.
    result = await apply_bundle(session, settings, bundle, blobs, _index(bundle))
    assert result["media_added"] == 0
    assets = (await session.execute(select(MediaAsset))).scalars().all()
    assert len(assets) == 1


async def test_restoring_onto_an_empty_host_reuploads_the_media(snapshot_db, tmp_path):
    session, settings = snapshot_db.session, snapshot_db.settings
    blobs = BlobStore(tmp_path / "blobs")
    await _seed_rich_site(session, settings)
    bundle = tmp_path / "b"
    await capture(session, settings, bundle, blobs)
    await _wipe(session)

    result = await apply_bundle(session, settings, bundle, blobs, _index(bundle))
    assert result["media_added"] == 1

    alpha = (
        await session.execute(select(Page).where(Page.slug == "alpha"))
    ).scalars().one()
    src = alpha.draft_data["content"][0]["props"]["src"]
    # Resolved to a real, host-local URL rather than left as a sentinel.
    assert src.startswith("/media/pagebuilder/")
    assert "asset://" not in json.dumps(alpha.draft_data)
