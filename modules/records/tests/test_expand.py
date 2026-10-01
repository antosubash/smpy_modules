"""``?expand=`` — depth-one relation resolution (design §9).

The three states of :class:`~sm_records.contracts.relations.ExpandedRef` are
what this file exists for, and two of them are easy to get subtly wrong:
*dangling* has to cover a trashed target **and** a purged one (a restorable
delete must not break what references it), and *restricted* has to mean the
caller learns nothing but the uuid they already hold.

The fourth test that matters is the statement count. §9 says "one batched
query per named field", and the generic list screen always expands — so a
per-row lookup here is a page of fifty records turning into fifty queries per
relation column, which is the regression no assertion on the *response* would
ever catch.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.relation_helpers import library, make_record, purge, trash


async def test_a_key_that_is_not_a_field_is_a_400_naming_it(client):
    await library(client)
    book = await make_record(client, "book", {"name": "Dune"})
    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=nope", headers=roles(ADMIN)
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["field"] == "nope"
    assert body["reason"] == "unknown"


async def test_a_key_that_is_not_a_relation_is_a_400_naming_it(client):
    """``name`` is a real field and still not expandable — the refusal has to
    say which, or a client cannot tell a typo from a wrong field type."""
    await library(client)
    book = await make_record(client, "book", {"name": "Dune"})
    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=name", headers=roles(ADMIN)
    )
    assert resp.status_code == 400
    assert resp.json()["field"] == "name"
    assert resp.json()["reason"] == "not_a_relation"


async def test_without_expand_nothing_is_resolved(client):
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    resp = await client.get(f"/api/records/types/book/records/{book['uuid']}", headers=roles(ADMIN))
    assert resp.status_code == 200
    assert resp.json()["expanded"] is None


async def test_a_single_reference_resolves(client):
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    (ref,) = resp.json()["expanded"]["author"]
    assert ref["type_key"] == "author"
    assert ref["uuid"] == author["uuid"]
    assert ref["display_title"] == "Herbert"
    assert ref["status"] == "draft"
    assert (ref["dangling"], ref["restricted"]) == (False, False)


async def test_a_to_many_relation_keeps_payload_order(client):
    """The UI renders ``expanded[key][i]`` next to ``data[key][i]``, so the
    order is the payload's and never the database's."""
    await library(client, many=True)
    names = ["Herbert", "Atwood", "Le Guin"]
    authors = [await make_record(client, "author", {"name": name}) for name in names]
    picked = [authors[2], authors[0], authors[1]]
    book = await make_record(
        client,
        "book",
        {
            "name": "Anthology",
            "author": [{"type": "author", "uuid": a["uuid"]} for a in picked],
        },
    )
    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    refs = resp.json()["expanded"]["author"]
    assert [ref["uuid"] for ref in refs] == [a["uuid"] for a in picked]
    assert [ref["display_title"] for ref in refs] == ["Le Guin", "Herbert", "Atwood"]


async def test_a_trashed_target_is_dangling_not_missing(client, records_app):
    _, db_state = records_app
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await trash(db_state, author["uuid"])

    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    (ref,) = resp.json()["expanded"]["author"]
    assert ref["dangling"] is True
    assert ref["display_title"] is None
    # Still echoed, so the editor can offer a restore rather than a blank row.
    assert ref["uuid"] == author["uuid"]


async def test_a_purged_target_is_dangling_too(client, records_app):
    _, db_state = records_app
    await library(client)
    author = await make_record(client, "author", {"name": "Herbert"})
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await purge(db_state, author["uuid"])

    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    (ref,) = resp.json()["expanded"]["author"]
    assert ref["dangling"] is True
    assert ref["display_title"] is None


async def test_a_narrowed_target_type_reads_as_restricted(client):
    """``allowed_roles`` on the *target* type, seen by a caller who lacks it:
    the reference is listed (it is in the payload the caller can already read)
    and nothing about the row comes back with it."""
    await library(client, author_roles=[ROLE_EDITOR])
    author = await make_record(client, "author", {"name": "Herbert"}, actor=ROLE_EDITOR)
    book = await make_record(
        client,
        "book",
        {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}},
        actor=ROLE_EDITOR,
    )
    url = f"/api/records/types/book/records/{book['uuid']}?expand=author"

    refused = await client.get(url, headers=roles(ROLE_VIEWER))
    (ref,) = refused.json()["expanded"]["author"]
    assert ref["restricted"] is True
    assert ref["display_title"] is None
    assert ref["dangling"] is False

    allowed = await client.get(url, headers=roles(ROLE_EDITOR))
    (ref,) = allowed.json()["expanded"]["author"]
    assert ref["restricted"] is False
    assert ref["display_title"] == "Herbert"


async def test_the_admin_wildcard_is_not_an_exception(client):
    """Narrowing has no exceptions (README § Permissions), and the read path
    reuses ``deps.check_type_roles``'s predicate rather than a second rule —
    so ``admin`` sees ``restricted`` here exactly as it is refused a write."""
    await library(client, author_roles=[ROLE_EDITOR])
    author = await make_record(client, "author", {"name": "Herbert"}, actor=ROLE_EDITOR)
    book = await make_record(
        client,
        "book",
        {"name": "Dune", "author": {"type": "author", "uuid": author["uuid"]}},
        actor=ROLE_EDITOR,
    )
    resp = await client.get(
        f"/api/records/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    (ref,) = resp.json()["expanded"]["author"]
    assert ref["restricted"] is True
