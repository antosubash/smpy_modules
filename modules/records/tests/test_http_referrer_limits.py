"""MINOR 2 / NOTE 1: what a ``restrict`` refusal says, and what a page costs.

The referrers panel counts a referrer whose type the caller may not read and
refuses to name it (``contracts.relations``); the delete refusal used to hand
back its uuid in a list whose length was that same count. And both the panel
and the editor's badge loaded every referring record to show one of them —
a graph that ``POST …/records/import`` can build a hundred thousand rows deep.
"""

from __future__ import annotations

import json

from sqlalchemy import event

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, api_record, api_type, roles
from tests.relation_helpers import rel_field, text_field

_API = "/api/records/types"
# --- MINOR 2 / NOTE 1: what a ``restrict`` refusal may say ----------------


async def test_a_restrict_refusal_counts_hidden_blockers_and_names_visible_ones(client):
    """A blocker in a type the caller may not read is counted, never named —
    the rule ``contracts.relations`` states for the panel. A blocker they
    *can* read is named, in the same body, so the refusal stays actionable.
    """
    await api_type(client, "author", [text_field("name")], display_field="name")
    await api_type(
        client,
        "public_book",
        [text_field("title"), rel_field("author", "author", "restrict")],
        display_field="title",
    )
    await api_type(
        client,
        "secret_book",
        [text_field("title"), rel_field("author", "author", "restrict")],
        actor=f"{ADMIN},{ROLE_EDITOR}",
        allowed_roles=[ROLE_EDITOR],
        display_field="title",
    )
    author = await api_record(client, "author", {"name": "A"}, actor=ROLE_EDITOR_TWO)
    ref = {"type": "author", "uuid": author["uuid"]}
    visible = await api_record(
        client, "public_book", {"title": "open", "author": ref}, actor=ROLE_EDITOR_TWO
    )
    hidden = await api_record(
        client, "secret_book", {"title": "classified", "author": ref}, actor=ROLE_EDITOR
    )

    refused = await client.delete(
        f"{_API}/author/records/{author['uuid']}", headers=roles(ROLE_EDITOR_TWO)
    )
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["referrers"] == [visible["uuid"]]
    assert hidden["uuid"] not in body["referrers"]
    assert body["hidden"] == 1
    assert body["more"] == 0
    # ``total`` is the same number ``detail`` speaks, as a field: a count a
    # client has to parse back out of a sentence stops being a count as soon
    # as the sentence is translated.
    assert body["total"] == 2
    assert body["detail"].startswith("2 record(s) still reference")
    # And the sentence does not name the record the caller asked to delete —
    # it is in the URL here, and in ``BulkFailure.uuid`` in a batch.
    assert author["uuid"] not in body["detail"]


async def test_the_blocker_list_is_capped_and_says_how_many_more(client):
    """``BLOCKER_CAP`` uuids and a ``more`` count, for the same reason
    ``ImportReport`` caps its errors: the graph can be built in bulk."""
    from sm_records.services._delete_plan import BLOCKER_CAP

    await api_type(client, "target", [text_field("name")], display_title=None, display_field="name")
    await api_type(
        client,
        "blocker",
        [text_field("title"), rel_field("target", "target", "restrict")],
        display_field="title",
    )
    target = await api_record(client, "target", {"name": "T"})
    rows = [
        {
            "data": {
                "title": f"b{i}",
                "target": {"type": "target", "uuid": target["uuid"]},
            }
        }
        for i in range(BLOCKER_CAP + 3)
    ]
    loaded = await client.post(
        f"{_API}/blocker/records/import?format=json&dry_run=false&mode=create",
        content=json.dumps(rows).encode(),
        headers={**roles(ADMIN), "content-type": "application/json"},
    )
    assert loaded.status_code == 200, loaded.text[:300]

    refused = await client.delete(f"{_API}/target/records/{target['uuid']}", headers=roles(ADMIN))
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert len(body["referrers"]) == BLOCKER_CAP
    assert body["more"] == 3
    assert body["hidden"] == 0
    assert body["total"] == BLOCKER_CAP + 3
    assert body["detail"].startswith(f"{BLOCKER_CAP + 3} record(s) still reference")


async def _statements(client, url: str) -> int:
    """How many statements one request issues."""
    engine = client.db_state.engine.sync_engine
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        resp = await client.get(url, headers=roles(ADMIN))
        assert resp.status_code == 200, resp.text
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(seen)


async def test_a_referrers_page_costs_the_same_at_any_scale(client):
    """The panel used to load every referring record to show one of them, and
    the editor's badge did it again for a number. Both are counted and
    windowed in SQL now — so the page, and the statements behind it, do not
    grow with the graph."""
    await api_type(client, "star", [text_field("name")], display_field="name")
    await api_type(
        client,
        "planet",
        [text_field("title"), rel_field("star", "star", "set_null")],
        display_field="title",
    )
    star = await api_record(client, "star", {"name": "Sol"})
    panel = f"{_API}/star/records/{star['uuid']}/referrers?page_size=1"

    costs = []
    for batch in (40, 160):
        rows = [
            {"data": {"title": f"p{batch}-{i}", "star": {"type": "star", "uuid": star["uuid"]}}}
            for i in range(batch)
        ]
        loaded = await client.post(
            f"{_API}/planet/records/import?format=json&dry_run=false&mode=create",
            content=json.dumps(rows).encode(),
            headers={**roles(ADMIN), "content-type": "application/json"},
        )
        assert loaded.status_code == 200, loaded.text[:300]
        costs.append(await _statements(client, panel))

    assert costs[0] == costs[1], costs
    page = await client.get(panel, headers=roles(ADMIN))
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == 200
