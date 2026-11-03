"""test_public_api cases."""

from __future__ import annotations
from tests.support.app_harness import ADMIN, roles
from tests.support.public_api_cases import _field, _make_type, _make_record, _article, _PREFIX, _PUBLIC_SHAPE, _UNKNOWN_UUID


async def test_an_unindexed_field_is_a_400_naming_it(public_client):
    await _article(public_client)
    resp = await public_client.get(f"{_PREFIX}/article?filter=body:eq:World")
    assert resp.status_code == 400
    assert "body" in resp.json()["detail"]


async def test_a_nonexistent_field_is_a_400_naming_it(public_client):
    await _article(public_client)
    resp = await public_client.get(f"{_PREFIX}/article?filter=nope:eq:1")
    assert resp.status_code == 400
    assert "nope" in resp.json()["detail"]
    sorted_by = await public_client.get(f"{_PREFIX}/article?sort=nope")
    assert sorted_by.status_code == 400


async def test_a_field_mid_reindex_is_a_400_and_never_the_admin_409(public_client, records_app):
    """§10: the difference between "cannot" and "cannot right now" is
    operational state an anonymous caller has no business seeing — and the
    same query on the admin API still answers 409."""
    from sm_records.models import RecordType
    from sqlalchemy import select

    _, db_state = records_app
    await _article(public_client)
    async with db_state.session_factory() as session:
        rtype = (
            (await session.execute(select(RecordType).where(RecordType.key == "article")))
            .scalars()
            .first()
        )
        rtype.reindex_pending = {"title": "2026-09-19T10:00:00+00:00"}
        session.add(rtype)
        await session.commit()

    anonymous = await public_client.get(f"{_PREFIX}/article?filter=title:eq:Hello")
    assert anonymous.status_code == 400
    assert "title" in anonymous.json()["detail"]
    assert "reindex" not in anonymous.text.lower()

    admin = await public_client.get(
        "/api/records/types/article/records?filter=title:eq:Hello", headers=roles(ADMIN)
    )
    assert admin.status_code == 409
    assert admin.json()["reason"] == "reindexing"


async def test_expand_and_trashed_are_ignored_not_honoured(public_client):
    """Neither is a parameter here: §10 refuses to let an anonymous caller
    turn one request into a batch of joins against types that may be private,
    and the trash is not public content. Unknown parameters are ignored."""
    record = await _article(public_client)
    trashed = await public_client.delete(
        f"/api/records/types/article/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert trashed.status_code == 204

    listed = await public_client.get(f"{_PREFIX}/article?trashed=true&expand=title")
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_page_size_is_clamped_not_refused(public_client):
    await _make_type(public_client, "article", is_public=True)
    for index in range(3):
        await _make_record(public_client, "article", {"title": f"t-{index}"})

    clamped = await public_client.get(f"{_PREFIX}/article?page_size=100000")
    assert clamped.status_code == 200
    assert clamped.json()["page_size"] == 200
    assert len(clamped.json()["items"]) == 3

    paged = await public_client.get(f"{_PREFIX}/article?page_size=2&page=2")
    assert paged.json()["page"] == 2
    assert len(paged.json()["items"]) == 1
    assert paged.json()["total"] == 3


async def test_head_answers_without_a_body(public_client):
    record = await _article(public_client)
    for url in (f"{_PREFIX}/article", f"{_PREFIX}/article/{record['uuid']}"):
        resp = await public_client.head(url)
        assert resp.status_code == 200, url
        assert resp.content == b""


async def test_the_admin_api_is_still_gated_for_the_same_caller(public_client):
    """The public router adds no authentication — and takes none away."""
    await _article(public_client)
    assert (await public_client.get("/api/records/types/article/records")).status_code == 401
    assert (await public_client.get("/admin/records/article")).status_code == 401
