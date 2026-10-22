"""The Pages and Media search sections stay inside one tenant (#130).

``test_search`` pins the Pages section; Media had no such test. Both now go
through ``pagebuilder.contracts``, so these drive the whole screen
(:func:`news.search_service.search`) rather than the seam, and check the hits
that reach it as well as the totals.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from news import search_service
from news.integrations import pagebuilder as pb
from simple_module_db import tenant_context

#: Unbound: the suite otherwise binds "default", and each test here states the
#: tenant it runs in — none (a single-tenant host) or one it binds itself.
pytestmark = [
    pytest.mark.skipif(not pb.available(), reason="pagebuilder is an optional extra"),
    pytest.mark.unbound_tenant,
]


async def _asset(db, name: str, *, tenant: str = "default"):
    from pagebuilder.models import MediaAsset

    asset = MediaAsset(
        tenant_id=tenant, filename=f"{tenant}-{name}", original_filename=name,
        content_type="image/png",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def _page(db, slug: str, *, tenant: str = "default", published: bool = True):
    from pagebuilder.models import Page, PageStatus

    page = Page(
        tenant_id=tenant, slug=slug, title=slug,
        status=PageStatus.PUBLISHED if published else PageStatus.DRAFT, draft_data={},
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


async def test_another_tenants_media_is_not_searched(db) -> None:
    """No tenant bound is a single-tenant host: the framework filters nothing,
    so the search must pin itself to the default tenant."""
    ours = await _asset(db, "basalt-ours.png")
    await _asset(db, "basalt-theirs.png", tenant="other")

    results = await search_service.search(db, "basalt")

    assert [(hit.id, hit.title) for hit in results.media] == [(ours.id, "basalt-ours.png")]
    assert results.media[0].subtitle == "image/png"
    assert results.media_total == 1


async def test_a_bound_tenant_sees_only_its_own_media_and_pages(db) -> None:
    """A multi-tenant request: the bound tenant is the one searched, and the
    default tenant's rows are as foreign as anyone else's."""
    await _asset(db, "gneiss.png")
    await _page(db, "gneiss-default")
    theirs = await _asset(db, "gneiss.png", tenant="acme")
    page = await _page(db, "gneiss-acme", tenant="acme")

    with tenant_context("acme"):
        results = await search_service.search(db, "gneiss")

    assert [hit.id for hit in results.media] == [theirs.id]
    assert results.media_total == 1
    assert [hit.id for hit in results.pages] == [page.id]
    assert results.page_total == 1


async def test_a_strict_session_with_no_tenant_finds_no_media(db, db_state) -> None:
    await _asset(db, "schist.png")
    db_state.tenant_strict = True
    try:
        hits, total = await pb.search_media(db, "%schist%", limit=10)
    finally:
        db_state.tenant_strict = False

    assert hits == []
    assert total == 0


async def test_drafts_are_left_out_unless_asked_for(db) -> None:
    """The status rule moved into pagebuilder with the query; it must still be
    the published *enum* it compares against, not a string that drifts."""
    published = await _page(db, "marble-live")
    await _page(db, "marble-draft", published=False)

    editor = await search_service.search(db, "marble")
    reader = await search_service.search(db, "marble", include_drafts=False)

    assert editor.page_total == 2
    assert [hit.id for hit in reader.pages] == [published.id]
    assert reader.pages[0].subtitle == "marble-live · published"


def test_the_seam_reads_pagebuilder_only_through_its_contracts() -> None:
    """The point of #130: nothing behind pagebuilder's public package — its
    models above all — is imported by the search seam. ``import pagebuilder``
    alone is the availability probe."""
    tree = ast.parse(pathlib.Path(pb.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names if a.name.startswith("pagebuilder")}
        elif isinstance(node, ast.ImportFrom) and node.module == "pagebuilder":
            imported |= {f"pagebuilder.{a.name}" for a in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pagebuilder"):
            imported.add(node.module)

    assert imported == {"pagebuilder", "pagebuilder.contracts"}
