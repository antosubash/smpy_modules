"""``?expand=`` costs one query per named field, and both admin screens use it.

Split from ``test_expand.py`` for the 300-line cap, along the seam that
matters: that file asserts what a reference *reads back as*, this one asserts
what resolving it *costs* and who asks for it. §9's "one batched query per
named field" is the rule the generic list screen depends on — a per-row lookup
turns a page of fifty into fifty queries per relation column — and no
assertion on a response body would ever notice it breaking.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles
from tests.perf._bench import capture
from tests.relation_helpers import INERTIA, field, library, make_record, make_type


async def test_one_statement_per_expanded_field_whatever_the_page_size(client, records_app):
    """§9's "one batched query per named field", asserted as a hard number.

    Two relation fields over four records: two statements of the expansion
    shape, not eight. The counter is the perf suite's
    ``before_cursor_execute`` capture — the same one the perf tests use to
    make "how many round trips" a property of the code.
    """
    _, db_state = records_app
    await make_type(client, "author", [field("name", "text")])
    await make_type(client, "house", [field("name", "text")])
    await make_type(
        client,
        "book",
        [
            field("name", "text"),
            field("author", "relation", target_type="author"),
            field("publisher", "relation", target_type="house"),
        ],
    )
    for index in range(4):
        author = await make_record(client, "author", {"name": f"author-{index}"})
        house = await make_record(client, "house", {"name": f"house-{index}"})
        await make_record(
            client,
            "book",
            {
                "name": f"book-{index}",
                "author": {"type": "author", "uuid": author["uuid"]},
                "publisher": {"type": "house", "uuid": house["uuid"]},
            },
        )

    with capture(db_state.engine) as seen:
        resp = await client.get(
            "/api/records/types/book/records?expand=author,publisher", headers=roles(ADMIN)
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 4
    assert all(item["expanded"]["author"] for item in resp.json()["items"])
    batched = [sql for sql, _ in seen.statements if "records_record.uuid IN" in sql]
    assert len(batched) == 2, batched


async def test_a_duplicate_key_costs_one_query(client, records_app):
    """``expand=author,author`` is one field, deduplicated in ``parse_expand``."""
    _, db_state = records_app
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    with capture(db_state.engine) as seen:
        resp = await client.get(
            "/api/records/types/book/records?expand=author,author", headers=roles(ADMIN)
        )
    assert resp.status_code == 200
    assert len([sql for sql, _ in seen.statements if "records_record.uuid IN" in sql]) == 1


async def test_the_list_view_always_expands_every_relation_column(client):
    """§9: the generic list screen is the one caller that always passes it —
    a column of bare UUIDs is not a list screen. The props carry the map on
    each item, so the page needs no second request to render a title."""
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    resp = await client.get("/admin/records/book", headers={**roles(ADMIN), **INERTIA})
    assert resp.status_code == 200
    (item,) = resp.json()["props"]["records"]["items"]
    (ref,) = item["expanded"]["author"]
    assert ref["display_title"] == "Herbert"


async def test_the_editor_view_expands_and_counts_referrers(client):
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    resp = await client.get(
        f"/admin/records/book/{book['uuid']}", headers={**roles(ADMIN), **INERTIA}
    )
    assert resp.status_code == 200
    props = resp.json()["props"]
    (ref,) = props["record"]["expanded"]["author"]
    assert ref["display_title"] == "Herbert"
    # The book references the author, and nothing references the book.
    assert props["referrer_count"] == 0

    resp = await client.get(
        f"/admin/records/author/{author['uuid']}", headers={**roles(ADMIN), **INERTIA}
    )
    assert resp.json()["props"]["referrer_count"] == 1
