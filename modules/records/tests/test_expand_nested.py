"""``?expand=a.b`` — relation expansion past depth one (#81).

What depth one promised has to hold at every level, and the tests below are
one per promise: the next level nests under a *resolved* entry, a cycle stops
rather than repeats, the depth and hop caps refuse before anything is read,
``restricted`` is decided per hop and hides what lies beneath it, every hop is
one batched statement whatever the page size, and the budget refuses a level
before it is read. Tenant isolation at depth is in
``test_tenancy_isolation_records.py`` beside the depth-one case.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_records.constants import EXPAND_DEPTH_CAP
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.perf._bench import capture
from tests.relation_helpers import field, make_record, make_type

_BOOKS = "/api/records/types/book/records"
_PEOPLE = "/api/records/types/person/records"


def _ref(type_key: str, record: dict) -> dict:
    return {"type": type_key, "uuid": record["uuid"]}


async def _chain(client, *, house_roles: list[str] | None = None):
    """``book.author -> author``, ``author.publisher -> house``: two hops."""
    await make_type(client, "house", [field("name", "text")], allowed_roles=house_roles or [])
    await make_type(
        client,
        "author",
        [field("name", "text"), field("publisher", "relation", target_type="house")],
    )
    await make_type(
        client,
        "book",
        [field("name", "text"), field("author", "relation", target_type="author")],
    )


async def _book(client, index: int = 0, *, actor: str = ADMIN) -> dict:
    house = await make_record(client, "house", {"name": f"house-{index}"}, actor=actor)
    author = await make_record(
        client,
        "author",
        {"name": f"author-{index}", "publisher": _ref("house", house)},
        actor=actor,
    )
    return await make_record(
        client, "book", {"name": f"book-{index}", "author": _ref("author", author)}, actor=actor
    )


async def test_a_dotted_path_nests_the_next_level_under_the_resolved_entry(client):
    await _chain(client)
    book = await _book(client)
    resp = await client.get(
        f"{_BOOKS}/{book['uuid']}?expand=author.publisher", headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    (author,) = resp.json()["expanded"]["author"]
    assert author["display_title"] == "author-0"
    (house,) = author["expanded"]["publisher"]
    assert house["display_title"] == "house-0"
    assert house["expanded"] is None  # the path ends here
    assert (house["dangling"], house["restricted"], house["cycle"]) == (False, False, False)


async def test_depth_one_is_unchanged(client):
    """A flat key still resolves one level and nests nothing."""
    await _chain(client)
    book = await _book(client)
    resp = await client.get(f"{_BOOKS}/{book['uuid']}?expand=author", headers=roles(ADMIN))
    (author,) = resp.json()["expanded"]["author"]
    assert author["expanded"] is None


async def test_an_unknown_nested_key_is_a_400_naming_its_whole_path(client):
    """Refused from the schema, so an empty page refuses it too."""
    await _chain(client)
    resp = await client.get(f"{_BOOKS}?expand=author.nope", headers=roles(ADMIN))
    assert resp.status_code == 400
    assert (resp.json()["field"], resp.json()["reason"]) == ("author.nope", "unknown")
    resp = await client.get(f"{_BOOKS}?expand=author.name", headers=roles(ADMIN))
    assert (resp.json()["field"], resp.json()["reason"]) == ("author.name", "not_a_relation")


@pytest.mark.parametrize("query", ["author..publisher", ".author", "author."])
async def test_an_empty_segment_is_a_400(client, query):
    await _chain(client)
    resp = await client.get(f"{_BOOKS}?expand={query}", headers=roles(ADMIN))
    assert resp.status_code == 400
    assert "expand" in resp.json()["detail"]


async def test_a_path_past_max_expand_depth_is_a_400_before_anything_is_read(client):
    await _chain(client)
    settings = client.app.state.sm_records.settings
    deep = ".".join(["author"] * (settings.max_expand_depth + 1))
    resp = await client.get(f"{_BOOKS}?expand={deep}", headers=roles(ADMIN))
    assert resp.status_code == 400
    assert "levels deep" in resp.json()["detail"]


def test_max_expand_depth_has_a_hard_cap():
    """Whatever an operator stores, five levels is the ceiling."""
    with pytest.raises(ValidationError):
        RecordsSettings(max_expand_depth=EXPAND_DEPTH_CAP + 1)
    assert RecordsSettings(max_expand_depth=EXPAND_DEPTH_CAP).max_expand_depth == EXPAND_DEPTH_CAP


async def test_too_many_hops_is_a_400(client):
    """``a.b`` is two hops, ``a`` beside it adds none."""
    await _chain(client)
    client.app.state.sm_records.settings.max_expand_paths = 2
    ok = await client.get(f"{_BOOKS}?expand=author,author.publisher", headers=roles(ADMIN))
    assert ok.status_code == 200, ok.text
    client.app.state.sm_records.settings.max_expand_paths = 1
    refused = await client.get(f"{_BOOKS}?expand=author.publisher", headers=roles(ADMIN))
    assert refused.status_code == 400
    assert "hops" in refused.json()["detail"]


async def test_a_restricted_hop_hides_everything_beneath_it(client):
    """``house`` narrows to editors: a viewer gets the author, a restricted
    publisher, and nothing below it — not even a refusal of a key the
    restricted type does not have, which would name its fields."""
    await _chain(client, house_roles=[ROLE_EDITOR])
    book = await _book(client, actor=ROLE_EDITOR)
    url = f"{_BOOKS}/{book['uuid']}?expand=author.publisher"

    viewer = await client.get(url, headers=roles(ROLE_VIEWER))
    (author,) = viewer.json()["expanded"]["author"]
    assert author["display_title"] == "author-0"
    (house,) = author["expanded"]["publisher"]
    assert (house["restricted"], house["display_title"], house["expanded"]) == (True, None, None)

    editor = await client.get(url, headers=roles(ROLE_EDITOR))
    (house,) = editor.json()["expanded"]["author"][0]["expanded"]["publisher"]
    assert house["display_title"] == "house-0"

    probe = f"{url}.nope"
    assert (await client.get(probe, headers=roles(ROLE_VIEWER))).status_code == 200
    refused = await client.get(probe, headers=roles(ROLE_EDITOR))
    assert refused.status_code == 400
    assert refused.json()["field"] == "author.publisher.nope"


async def test_a_cycle_resolves_once_and_stops(client):
    """``a.friend -> b``, ``b.friend -> a``: three levels asked, and the walk
    stops at the first entry that is already on its own chain."""
    await make_type(
        client,
        "person",
        [field("name", "text"), field("friend", "relation", target_type="person")],
    )
    a = await make_record(client, "person", {"name": "a"})
    b = await make_record(client, "person", {"name": "b", "friend": _ref("person", a)})
    resp = await client.put(
        f"{_PEOPLE}/{a['uuid']}",
        json={"expected_version": a["version"], "data": {"name": "a", "friend": _ref("person", b)}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        f"{_PEOPLE}/{a['uuid']}?expand=friend.friend.friend", headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    (first,) = resp.json()["expanded"]["friend"]
    assert (first["uuid"], first["cycle"]) == (b["uuid"], False)
    (back,) = first["expanded"]["friend"]
    assert (back["uuid"], back["display_title"], back["cycle"]) == (a["uuid"], "a", True)
    assert back["expanded"] is None


async def test_one_statement_per_hop_whatever_the_page_size(client, records_app):
    """Four books, ``author.publisher``: one ``IN`` for the authors and one
    for the houses — two, not four plus four."""
    _, db_state = records_app
    await _chain(client)
    for index in range(4):
        await _book(client, index)
    with capture(db_state.engine) as seen:
        resp = await client.get(f"{_BOOKS}?expand=author.publisher", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 4
    assert all(item["expanded"]["author"][0]["expanded"]["publisher"] for item in items)
    batched = [sql for sql, _ in seen.statements if "records_record.uuid IN" in sql]
    assert len(batched) == 2, batched
    types = [sql for sql, _ in seen.statements if 'records_type."key" IN' in sql]
    assert len(types) == 2, types  # one per level


async def test_a_level_over_the_budget_is_refused_before_it_is_read(client):
    """Depth one is outside the budget; the deeper level is counted first."""
    await _chain(client)
    for index in range(3):
        await _book(client, index)
    client.app.state.sm_records.settings.max_expand_refs = 3
    ok = await client.get(f"{_BOOKS}?expand=author.publisher", headers=roles(ADMIN))
    assert ok.status_code == 200, ok.text
    client.app.state.sm_records.settings.max_expand_refs = 2
    refused = await client.get(f"{_BOOKS}?expand=author.publisher", headers=roles(ADMIN))
    assert refused.status_code == 400
    assert (refused.json()["field"], refused.json()["reason"]) == (
        "author.publisher",
        "expand_budget",
    )
    flat = await client.get(f"{_BOOKS}?expand=author", headers=roles(ADMIN))
    assert flat.status_code == 200
