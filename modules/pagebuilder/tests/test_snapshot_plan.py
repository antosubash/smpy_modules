from __future__ import annotations

import json

import pytest
from pagebuilder.models import Page, PageRedirect, PageStatus
from pagebuilder.snapshots.plan import build_plan

pytestmark = pytest.mark.asyncio


def _bundle(tmp_path, pages, redirects=None, layout=None):
    root = tmp_path / "bundle"
    (root / "pages").mkdir(parents=True, exist_ok=True)
    for payload in pages:
        full = {
            "slug": payload["slug"],
            "title": payload.get("title", payload["slug"].title()),
            "status": payload.get("status", "draft"),
            "parent_slug": None,
            "draft_data": payload.get("draft_data", {}),
            "published_data": None,
            **{k: v for k, v in payload.items() if k not in ("slug", "draft_data")},
        }
        (root / "pages" / f"{payload['slug']}.json").write_text(json.dumps(full))
    (root / "redirects.json").write_text(json.dumps(redirects or []))
    (root / "layout.json").write_text(json.dumps(layout or {}))
    return root


async def test_plan_classifies_pages(snapshot_db, tmp_path):
    session = snapshot_db.session
    session.add(Page(slug="kept", title="Kept", draft_data={"content": []}))
    session.add(Page(slug="changed", title="Changed", draft_data={"content": ["old"]}))
    session.add(Page(slug="extra", title="Extra"))
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [
            {"slug": "kept", "title": "Kept", "draft_data": {"content": []}},
            {"slug": "changed", "title": "Changed", "draft_data": {"content": ["new"]}},
            {"slug": "fresh", "title": "Fresh"},
        ],
    )
    plan = await build_plan(session, bundle, {})

    assert [p["slug"] for p in plan["pages"]["new"]] == ["fresh"]
    assert [p["slug"] for p in plan["pages"]["overwritten"]] == ["changed"]
    assert [p["slug"] for p in plan["pages"]["unchanged"]] == ["kept"]
    # Restore never deletes: a live page the bundle omits is reported, not lost.
    assert [p["slug"] for p in plan["pages"]["untouched"]] == ["extra"]


async def test_a_metadata_only_edit_still_counts_as_overwritten(snapshot_db, tmp_path):
    session = snapshot_db.session
    session.add(Page(slug="home", title="Old title", draft_data={"content": []}))
    await session.flush()

    bundle = _bundle(
        tmp_path, [{"slug": "home", "title": "New title", "draft_data": {"content": []}}]
    )
    plan = await build_plan(session, bundle, {})
    assert [p["slug"] for p in plan["pages"]["overwritten"]] == ["home"]


async def test_status_change_alone_counts_as_overwritten(snapshot_db, tmp_path):
    session = snapshot_db.session
    session.add(
        Page(
            slug="home",
            title="Home",
            status=PageStatus.DRAFT,
            draft_data={"content": []},
        )
    )
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [
            {
                "slug": "home",
                "title": "Home",
                "status": "published",
                "draft_data": {"content": []},
            }
        ],
    )
    plan = await build_plan(session, bundle, {})
    assert [p["slug"] for p in plan["pages"]["overwritten"]] == ["home"]


async def test_overwritten_pages_carry_a_block_level_summary(snapshot_db, tmp_path):
    session = snapshot_db.session
    session.add(
        Page(
            slug="home",
            title="Home",
            draft_data={"content": [{"type": "Hero", "props": {"id": "a", "t": "x"}}]},
        )
    )
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [
            {
                "slug": "home",
                "title": "Home",
                "draft_data": {
                    "content": [
                        {"type": "Hero", "props": {"id": "a", "t": "y"}},
                        {"type": "Faq", "props": {"id": "b"}},
                    ]
                },
            }
        ],
    )
    plan = await build_plan(session, bundle, {})
    entry = plan["pages"]["overwritten"][0]
    assert entry["changed"] == 1
    assert entry["added"] == 1
    assert entry["removed"] == 0


async def test_sentinels_resolve_before_comparing_so_media_is_not_false_drift(
    snapshot_db, tmp_path
):
    session = snapshot_db.session
    live_url = "/media/pagebuilder/uuid1.jpg"
    session.add(
        Page(
            slug="home",
            title="Home",
            draft_data={"content": [{"props": {"src": live_url}}]},
        )
    )
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [
            {
                "slug": "home",
                "title": "Home",
                "draft_data": {"content": [{"props": {"src": "asset://hero.jpg"}}]},
            }
        ],
    )
    plan = await build_plan(session, bundle, {"hero.jpg": live_url})
    assert [p["slug"] for p in plan["pages"]["unchanged"]] == ["home"]


async def test_redirect_plan_reports_added_removed_and_dropped(snapshot_db, tmp_path):
    session = snapshot_db.session
    page = Page(slug="home", title="Home")
    session.add(page)
    await session.flush()
    session.add(PageRedirect(from_slug="stale", page_id=page.id))
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [{"slug": "home", "title": "Home"}],
        redirects=[
            {"from_slug": "old", "to_slug": "home"},
            {"from_slug": "orphan", "to_slug": "nowhere"},
        ],
    )
    plan = await build_plan(session, bundle, {})
    assert plan["redirects"]["added"] == ["old"]
    assert plan["redirects"]["removed"] == ["stale"]
    # An unresolvable target is a 404 generator, so it is dropped and named.
    assert plan["redirects"]["dropped"] == ["orphan"]


async def test_layout_plan_counts_blocks(snapshot_db, tmp_path):
    bundle = _bundle(
        tmp_path,
        [],
        layout={
            "header_data": {"content": [1, 2, 3]},
            "footer_data": {"content": [1]},
        },
    )
    plan = await build_plan(snapshot_db.session, bundle, {})
    assert plan["layout"] == {
        "header": 3,
        "footer": 1,
        "header_present": True,
        "footer_present": True,
    }


async def test_layout_plan_marks_an_absent_side_as_unchanged(snapshot_db, tmp_path):
    """A bundle with no layout leaves the live one alone, and says so.

    `LayoutService.update` reads None as "no change requested", so reporting a
    bare 0 told an approver the header would be emptied when it would not.
    """
    bundle = _bundle(tmp_path, [], layout={})
    plan = await build_plan(snapshot_db.session, bundle, {})
    assert plan["layout"] == {
        "header": 0,
        "footer": 0,
        "header_present": False,
        "footer_present": False,
    }


async def test_a_trashed_slug_is_reported_as_overwritten_not_new(snapshot_db, tmp_path):
    """The plan has to describe the apply that will happen.

    ``_restore_pages`` matches slugs against every page, trashed included, so a
    bundled slug claimed by a binned page overwrites and revives it. Calling
    that "created" would promise an approver a fresh page while recoverable
    content is destroyed.
    """
    from datetime import UTC, datetime

    session = snapshot_db.session
    session.add(
        Page(
            slug="home",
            title="Binned",
            draft_data={"content": ["old"]},
            deleted_at=datetime.now(UTC),
        )
    )
    await session.flush()

    bundle = _bundle(tmp_path, [{"slug": "home", "title": "Home"}])
    plan = await build_plan(session, bundle, {})

    assert plan["pages"]["new"] == []
    assert [e["slug"] for e in plan["pages"]["overwritten"]] == ["home"]
    assert plan["pages"]["overwritten"][0]["revived"] is True
    # Nor "untouched": that list promises pages the restore leaves alone.
    assert plan["pages"]["untouched"] == []


async def test_an_identical_trashed_page_still_counts_as_a_change(snapshot_db, tmp_path):
    """Reviving is itself a change, even when every field already matches."""
    from datetime import UTC, datetime

    session = snapshot_db.session
    session.add(
        Page(
            slug="home",
            title="Home",
            draft_data={},
            published_data=None,
            deleted_at=datetime.now(UTC),
        )
    )
    await session.flush()

    bundle = _bundle(tmp_path, [{"slug": "home", "title": "Home", "draft_data": {}}])
    plan = await build_plan(session, bundle, {})

    assert plan["pages"]["unchanged"] == []
    assert [e["slug"] for e in plan["pages"]["overwritten"]] == ["home"]


async def test_a_redirect_is_never_both_removed_and_dropped(snapshot_db, tmp_path):
    """One redirect must not be counted twice on the approval screen.

    ``removed`` and ``dropped`` are rendered as separate badges, so an overlap
    would show two numbers for a single redirect and overstate the blast
    radius. Dropped wins: it is the more specific fact and it names the slug.
    """
    session = snapshot_db.session
    page = Page(slug="home", title="Home")
    session.add(page)
    await session.flush()
    session.add(PageRedirect(from_slug="shared", page_id=page.id))
    await session.flush()

    bundle = _bundle(
        tmp_path,
        [{"slug": "home", "title": "Home"}],
        redirects=[{"from_slug": "shared", "to_slug": "nowhere"}],
    )
    plan = await build_plan(session, bundle, {})

    assert plan["redirects"]["dropped"] == ["shared"]
    assert plan["redirects"]["removed"] == []
