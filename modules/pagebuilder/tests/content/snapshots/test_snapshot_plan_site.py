from __future__ import annotations

import pytest
from pagebuilder.content.snapshots.plan import build_plan
from pagebuilder.models import Page, PageRedirect

from tests.support.snapshot_plan import _bundle

pytestmark = pytest.mark.asyncio


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
