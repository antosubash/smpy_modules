"""The anonymous read API (design §10), exercised with no session at all.

Every request in this file goes out **without** an ``X-Test-Roles`` header,
which is the harness's stand-in for an unauthenticated caller
(``app_harness._HeaderAuthMiddleware`` leaves ``request.state.user`` unset,
and ``RequiresPermission`` turns that into a 401 on every admin route). If any
of these start needing a header, the router has grown an auth dependency it
must not have.

The rules under test, in the order §10 states them: a private type is a 404
indistinguishable from a missing one, by key *and* by uuid; only published,
never-trashed records are served; the response shape drops the audit columns
and ``_orphaned``; the filter grammar is the admin one but every refusal is a
400 naming the field, never the admin's 409; and ``expand`` is not a parameter
here at all.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles

_PREFIX = "/api/records/public"
_PUBLIC_SHAPE = {
    "uuid",
    "slug",
    "locale",
    "translations",
    "display_title",
    "published_at",
    "data",
}
_UNKNOWN_UUID = "0" * 32


def _field(key: str, type_: str, *, indexed: bool = True, **options) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "indexed": indexed,
        "options": options,
    }


async def _make_type(client, key: str, *, is_public: bool, fields=None, **cols) -> dict:
    resp = await client.post(
        "/api/records/types",
        json={
            "key": key,
            "label": key.title(),
            "fields": fields or [_field("title", "text"), _field("body", "text", indexed=False)],
            "display_field": "title",
            "is_public": is_public,
            **cols,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_record(client, key: str, data: dict, *, status: str = "published") -> dict:
    resp = await client.post(
        f"/api/records/types/{key}/records",
        json={"data": data, "status": status},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _article(public_client):
    await _make_type(public_client, "article", is_public=True)
    return await _make_record(public_client, "article", {"title": "Hello", "body": "World"})


async def test_an_anonymous_caller_reads_a_public_type(public_client):
    record = await _article(public_client)

    listed = await public_client.get(f"{_PREFIX}/article")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert "set-cookie" not in {key.lower() for key in listed.headers}

    one = await public_client.get(f"{_PREFIX}/article/{record['uuid']}")
    assert one.status_code == 200
    assert one.json()["display_title"] == "Hello"
    assert one.json()["data"] == {"title": "Hello", "body": "World"}


async def test_the_shape_carries_no_audit_or_status_columns(public_client):
    """Fields are *removed from the shape*, not filtered from the query — so
    this asserts the exact key set, not the absence of one column."""
    record = await _article(public_client)
    one = await public_client.get(f"{_PREFIX}/article/{record['uuid']}")
    # ``locale``/``translations`` are Phase 5 §4.4: which language this is and
    # where its published siblings are. Still no ``status``, ``version``,
    # ``position`` or audit column — and no ``translation_group``, which is an
    # internal join key rather than an address.
    assert set(one.json()) == _PUBLIC_SHAPE

    listed = await public_client.get(f"{_PREFIX}/article")
    assert set(listed.json()) == {
        "items",
        "total",
        "total_capped",
        "next_cursor",
        "page",
        "page_size",
        # ``null`` unless files are anonymous — see ``tests/test_media.py``.
        "media_url_template",
    }
    assert listed.json()["media_url_template"] is None
    assert set(listed.json()["items"][0]) == _PUBLIC_SHAPE
    for absent in ("version", "created_by", "updated_at", "status", "invalid", "expanded"):
        assert absent not in listed.json()["items"][0]


async def test_orphaned_values_are_never_public(public_client, records_app):
    """``_orphaned`` is a deleted field's retained values — the admin's undo
    buffer (§8.2), and never site content."""
    from tests.app_harness import seed_record, seed_type

    _, db_state = records_app
    rtype = await seed_type(
        db_state,
        "note",
        [_field("title", "text")],
        display_field="title",
        is_public=True,
    )
    record = await seed_record(
        db_state,
        rtype,
        {"title": "Kept", "_orphaned": {"secret": "do not publish"}},
        status="published",
        display_title="Kept",
    )
    resp = await public_client.get(f"{_PREFIX}/note/{record.uuid}")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"title": "Kept"}


async def test_a_private_type_is_404_by_key_and_by_uuid_alike(public_client):
    await _make_type(public_client, "secret", is_public=False)
    record = await _make_record(public_client, "secret", {"title": "Hidden", "body": "x"})

    by_key = await public_client.get(f"{_PREFIX}/secret")
    by_uuid = await public_client.get(f"{_PREFIX}/secret/{record['uuid']}")
    missing = await public_client.get(f"{_PREFIX}/no-such-type")

    assert by_key.status_code == by_uuid.status_code == missing.status_code == 404
    # Indistinguishable: a different body for "private" than for "missing"
    # turns the endpoint into an oracle for which type keys exist.
    assert by_key.json() == by_uuid.json() == missing.json()


async def test_a_draft_and_an_unknown_uuid_are_the_same_404(public_client):
    await _make_type(public_client, "article", is_public=True)
    draft = await _make_record(public_client, "article", {"title": "WIP"}, status="draft")

    hidden = await public_client.get(f"{_PREFIX}/article/{draft['uuid']}")
    unknown = await public_client.get(f"{_PREFIX}/article/{_UNKNOWN_UUID}")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()

    listed = await public_client.get(f"{_PREFIX}/article")
    assert listed.json()["total"] == 0


async def test_a_trashed_record_is_404_and_leaves_the_list(public_client):
    record = await _article(public_client)
    trashed = await public_client.delete(
        f"/api/records/types/article/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert trashed.status_code == 204

    assert (await public_client.get(f"{_PREFIX}/article/{record['uuid']}")).status_code == 404
    assert (await public_client.get(f"{_PREFIX}/article")).json()["total"] == 0


async def test_filters_and_sorts_work_over_indexed_fields(public_client):
    await _make_type(public_client, "article", is_public=True)
    await _make_record(public_client, "article", {"title": "Alpha", "body": "a"})
    await _make_record(public_client, "article", {"title": "Beta", "body": "b"})

    filtered = await public_client.get(f"{_PREFIX}/article?filter=title:eq:Beta")
    assert filtered.status_code == 200
    assert [item["display_title"] for item in filtered.json()["items"]] == ["Beta"]

    sorted_desc = await public_client.get(f"{_PREFIX}/article?sort=-title")
    assert [item["display_title"] for item in sorted_desc.json()["items"]] == ["Beta", "Alpha"]


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
