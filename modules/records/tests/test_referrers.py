"""The reverse relation query (design §9) and its honesty rule (§10).

``GET …/records/{uuid}/referrers`` answers "what points at this record" from
``records_index_ref``. Two properties are worth a test each and neither is
visible from the happy path:

* ``total`` counts every referrer, including the ones this caller may not see
  — the count the delete dialog quotes has to be the count a ``restrict``
  refusal will actually produce — while ``items`` omits them entirely.
* the trash is *included here* and *excluded from the delete path*. Those are
  opposite answers to the same query on purpose, so the delete-path assertions
  at the bottom of this file are as load-bearing as the listing ones.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.relation_helpers import INERTIA, field, make_record, make_type


async def _library(client, *, on_delete: str = "restrict", book_roles: list[str] | None = None):
    await make_type(client, "author", [field("name", "text")])
    await make_type(
        client,
        "book",
        [
            field("name", "text"),
            field("written_by", "relation", target_type="author", on_delete=on_delete),
        ],
        allowed_roles=book_roles or [],
    )


def _referrers_url(uuid: str, **params) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"/api/records/types/author/records/{uuid}/referrers" + (f"?{query}" if query else "")


async def test_a_referrer_carries_its_field_label_and_delete_behaviour(client):
    """The dialog says "3 orders reference this and will block the delete", so
    both the referring field's *label* and its ``on_delete`` are in the shape —
    the label read from the referring type's definition, not this one's."""
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "written_by": {"type": "author", "uuid": author["uuid"]}}
    )

    resp = await client.get(_referrers_url(author["uuid"]), headers=roles(ADMIN))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item == {
        "type_key": "book",
        "type_label": "Book",
        "uuid": book["uuid"],
        "display_title": "Dune",
        "field_key": "written_by",
        "field_label": "Written By",
        "on_delete": "restrict",
        "is_deleted": False,
    }


async def test_referrers_paginate(client):
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    for index in range(3):
        await make_record(
            client,
            "book",
            {"name": f"book-{index}", "written_by": {"type": "author", "uuid": author["uuid"]}},
        )

    first = await client.get(_referrers_url(author["uuid"], page_size=2), headers=roles(ADMIN))
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["total"] == 3

    second = await client.get(
        _referrers_url(author["uuid"], page=2, page_size=2), headers=roles(ADMIN)
    )
    assert len(second.json()["items"]) == 1
    assert second.json()["total"] == 3
    seen = {item["uuid"] for item in first.json()["items"] + second.json()["items"]}
    assert len(seen) == 3


async def test_a_referrer_the_caller_may_not_view_is_counted_but_not_listed(client):
    """§10: the count stays honest, the row does not leak. A caller outside
    the *referring* type's ``allowed_roles`` learns that something references
    this record — which a ``restrict`` refusal would tell them anyway — and
    nothing about what."""
    await _library(client, book_roles=[ROLE_EDITOR])
    author = await make_record(client, "author", {"name": "Herbert"})
    await make_record(
        client,
        "book",
        {"name": "Dune", "written_by": {"type": "author", "uuid": author["uuid"]}},
        actor=ROLE_EDITOR,
    )

    redacted = await client.get(_referrers_url(author["uuid"]), headers=roles(ROLE_VIEWER))
    assert redacted.status_code == 200
    assert redacted.json()["total"] == 1
    assert redacted.json()["items"] == []

    allowed = await client.get(_referrers_url(author["uuid"]), headers=roles(ROLE_EDITOR))
    assert [item["display_title"] for item in allowed.json()["items"]] == ["Dune"]


async def test_a_trashed_referrer_is_listed_and_marked(client):
    """Unlike the delete path, which drops it — see the two tests below. The
    panel has to show it, or a restore silently resurrects a reference the
    editor was never told about."""
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "written_by": {"type": "author", "uuid": author["uuid"]}}
    )
    trashed = await client.delete(
        f"/api/records/types/book/records/{book['uuid']}", headers=roles(ADMIN)
    )
    assert trashed.status_code == 204

    resp = await client.get(_referrers_url(author["uuid"]), headers=roles(ADMIN))
    assert resp.json()["total"] == 1
    (item,) = resp.json()["items"]
    assert item["uuid"] == book["uuid"]
    assert item["is_deleted"] is True


async def test_a_self_reference_is_not_its_own_referrer(client):
    """A record relating to itself would otherwise make its own ``restrict``
    field refuse its own delete — not a referential-integrity problem anybody
    has, so it is dropped from both the listing and the count."""
    await make_type(
        client,
        "node",
        [field("name", "text"), field("parent", "relation", target_type="node")],
    )
    node = await make_record(client, "node", {"name": "root"})
    updated = await client.put(
        f"/api/records/types/node/records/{node['uuid']}",
        json={
            "expected_version": node["version"],
            "data": {"name": "root", "parent": {"type": "node", "uuid": node["uuid"]}},
        },
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200

    resp = await client.get(
        f"/api/records/types/node/records/{node['uuid']}/referrers", headers=roles(ADMIN)
    )
    assert resp.json() == {"items": [], "total": 0}

    view = await client.get(
        f"/admin/records/node/{node['uuid']}", headers={**roles(ADMIN), **INERTIA}
    )
    assert view.json()["props"]["referrer_count"] == 0


async def test_referrer_count_counts_distinct_records(client):
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    for index in range(2):
        await make_record(
            client,
            "book",
            {"name": f"book-{index}", "written_by": {"type": "author", "uuid": author["uuid"]}},
        )
    view = await client.get(
        f"/admin/records/author/{author['uuid']}", headers={**roles(ADMIN), **INERTIA}
    )
    assert view.json()["props"]["referrer_count"] == 2


async def test_referrers_of_an_unknown_record_is_404(client):
    await _library(client)
    resp = await client.get(_referrers_url("0" * 32), headers=roles(ADMIN))
    assert resp.status_code == 404


async def test_the_delete_path_still_ignores_a_trashed_referrer(client):
    """The regression guard for ``referrers(include_deleted=...)``: the
    listing opts in, and the delete path must not. A trashed referrer neither
    blocks a ``restrict`` delete nor is followed by a ``cascade``."""
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "written_by": {"type": "author", "uuid": author["uuid"]}}
    )
    await client.delete(f"/api/records/types/book/records/{book['uuid']}", headers=roles(ADMIN))

    resp = await client.delete(
        f"/api/records/types/author/records/{author['uuid']}", headers=roles(ADMIN)
    )
    assert resp.status_code == 204


async def test_the_delete_path_still_blocks_on_a_live_referrer(client):
    await _library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "written_by": {"type": "author", "uuid": author["uuid"]}}
    )
    resp = await client.delete(
        f"/api/records/types/author/records/{author['uuid']}", headers=roles(ADMIN)
    )
    assert resp.status_code == 409
    assert resp.json()["referrers"] == [book["uuid"]]
