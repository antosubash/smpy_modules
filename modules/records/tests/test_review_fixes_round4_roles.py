"""Phase 4 review, the read surface: ``allowed_roles`` and the referrers panel.

Every test here failed before its fix. The theme is one decision — **design
§10's narrowing applies to reads, with the same refusal writes get** — and its
consequences for the panel that counts what points at a record.

Redaction was the alternative, and it protected nothing: the caller an
``?expand=`` told ``restricted`` could read the same record in full one
request later, list its type, and open the admin screen for it.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_MANAGER, ROLE_VIEWER, roles
from tests.relation_helpers import INERTIA, field, make_record, make_type

API = "/api/records"
VIEWS = "/admin/records"


async def _narrowed(client, *, key: str = "secret") -> dict:
    await make_type(client, key, [field("name", "text")], allowed_roles=[ROLE_EDITOR])
    return await make_record(client, key, {"name": "Classified"}, actor=ROLE_EDITOR)


async def test_every_record_read_of_a_narrowed_type_is_403(client):
    record = await _narrowed(client)
    for path in (
        f"{API}/types/secret/records",
        f"{API}/types/secret/records/{record['uuid']}",
        f"{API}/types/secret/records/{record['uuid']}/referrers",
        f"{API}/types/secret/records/{record['uuid']}/revisions",
    ):
        resp = await client.get(path, headers=roles(ROLE_VIEWER))
        assert resp.status_code == 403, path
        assert "Classified" not in resp.text


async def test_the_admin_wildcard_is_no_exception_on_a_read_either(client):
    """Narrowing has no wildcard exception on writes (README § Permissions),
    and a read that ignored that would be the hole the ``restricted`` badge
    was pretending to cover."""
    record = await _narrowed(client)
    resp = await client.get(f"{API}/types/secret/records/{record['uuid']}", headers=roles(ADMIN))
    assert resp.status_code == 403


async def test_the_included_role_still_reads_everything(client):
    record = await _narrowed(client)
    got = await client.get(
        f"{API}/types/secret/records/{record['uuid']}", headers=roles(ROLE_EDITOR)
    )
    assert got.status_code == 200
    assert got.json()["display_title"] == "Classified"


async def test_the_record_views_are_narrowed_too(client):
    """The Inertia screens read through the same dependency: a 403 on the API
    and a rendered list on the view is the same leak with a nicer font."""
    record = await _narrowed(client)
    for path in (f"{VIEWS}/secret", f"{VIEWS}/secret/new", f"{VIEWS}/secret/{record['uuid']}"):
        resp = await client.get(path, headers={**roles(ROLE_VIEWER), **INERTIA})
        assert resp.status_code == 403, path


async def test_the_type_list_omits_what_it_would_refuse(client):
    await _narrowed(client)
    await make_type(client, "open", [field("name", "text")])
    listed = await client.get(f"{API}/types", headers=roles(ROLE_VIEWER))
    assert [item["key"] for item in listed.json()["items"]] == ["open"]

    screen = await client.get(f"{VIEWS}/", headers={**roles(ROLE_VIEWER), **INERTIA})
    assert [item["key"] for item in screen.json()["props"]["types"]] == ["open"]


async def test_a_manager_is_never_locked_out_of_the_schema_screen(client):
    """The one exception, and the reason for it: ``allowed_roles`` is edited
    on the type, so narrowing that hid the type from its own manager would be
    a one-way door."""
    await _narrowed(client)
    got = await client.get(f"{API}/types/secret", headers=roles(ROLE_MANAGER))
    assert got.status_code == 200
    screen = await client.get(f"{VIEWS}/types/secret", headers={**roles(ROLE_MANAGER), **INERTIA})
    assert screen.status_code == 200

    widened = await client.put(
        f"{API}/types/secret",
        json={"allowed_roles": [], "expected_version": got.json()["version"]},
        headers=roles(ROLE_MANAGER),
    )
    assert widened.status_code == 200
    assert (
        await client.get(f"{API}/types/secret/records", headers=roles(ROLE_VIEWER))
    ).status_code == 200


# ---------------------------------------------------------------------------
# The referrers panel: total, hidden, items, and the badge over it
# ---------------------------------------------------------------------------


async def _graph(client) -> dict:
    """An ``author`` two ``open`` books and two ``private`` books point at,
    interleaved so a windowing bug shows up as a position."""
    await make_type(client, "author", [field("name", "text")])
    for key, allowed in (("open", []), ("private", [ROLE_EDITOR])):
        await make_type(
            client,
            key,
            [field("name", "text"), field("author", "relation", target_type="author")],
            allowed_roles=allowed,
        )
    author = await make_record(client, "author", {"name": "A"})
    ref = {"type": "author", "uuid": author["uuid"]}
    for key, name, actor in (
        ("open", "O1", ADMIN),
        ("private", "P1", ROLE_EDITOR),
        ("open", "O2", ADMIN),
        ("private", "P2", ROLE_EDITOR),
    ):
        await make_record(client, key, {"name": name, "author": ref}, actor=actor)
    return author


async def test_hidden_is_reported_and_paging_is_not_an_oracle(client):
    author = await _graph(client)
    base = f"{API}/types/author/records/{author['uuid']}/referrers"
    pages = []
    for page in range(1, 5):
        body = (
            await client.get(f"{base}?page={page}&page_size=1", headers=roles(ROLE_VIEWER))
        ).json()
        pages.append([item["display_title"] for item in body["items"]])
        assert body["total"] == 4
        assert body["hidden"] == 2
    # The visible rows are contiguous from page 1: an empty page no longer
    # says "there is something here you may not see".
    assert pages == [["O1"], ["O2"], [], []]


async def test_an_included_caller_sees_everything_and_hides_nothing(client):
    author = await _graph(client)
    body = (
        await client.get(
            f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ROLE_EDITOR)
        )
    ).json()
    assert body["total"] == 4
    assert body["hidden"] == 0
    assert len(body["items"]) == 4


async def test_the_badge_and_the_panel_count_the_same_thing(client):
    """One record referencing the target from two fields is two rows in the
    panel — it names the field — and one referrer in both counts."""
    await make_type(client, "author", [field("name", "text")])
    await make_type(
        client,
        "book",
        [
            field("name", "text"),
            field("writer", "relation", target_type="author"),
            field("editor", "relation", target_type="author"),
        ],
    )
    author = await make_record(client, "author", {"name": "A"})
    ref = {"type": "author", "uuid": author["uuid"]}
    await make_record(client, "book", {"name": "B", "writer": ref, "editor": ref})

    panel = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ADMIN)
    )
    view = await client.get(f"{VIEWS}/author/{author['uuid']}", headers={**roles(ADMIN), **INERTIA})
    assert panel.json()["total"] == 1
    assert len(panel.json()["items"]) == 2
    assert view.json()["props"]["referrer_count"] == panel.json()["total"]


async def test_the_badge_counts_what_the_caller_cannot_see(client):
    """The badge is deliberately unfiltered — it is a prompt to open the
    panel, and the panel's ``hidden`` is what explains the difference."""
    author = await _graph(client)
    view = await client.get(
        f"{VIEWS}/author/{author['uuid']}", headers={**roles(ROLE_VIEWER), **INERTIA}
    )
    panel = (
        await client.get(
            f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ROLE_VIEWER)
        )
    ).json()
    assert view.json()["props"]["referrer_count"] == panel["total"] == 4
    assert panel["hidden"] == 2
    assert len(panel["items"]) == 2


async def test_a_referring_record_removed_behind_the_module_counts_nowhere(client, records_app):
    """An out-of-band delete leaves ``records_index_ref`` rows behind. The
    badge counted them and the panel did not; now neither does."""
    from tests.relation_helpers import purge

    _app, db_state = records_app
    await make_type(client, "author", [field("name", "text")])
    await make_type(
        client, "book", [field("name", "text"), field("author", "relation", target_type="author")]
    )
    author = await make_record(client, "author", {"name": "A"})
    book = await make_record(
        client, "book", {"name": "B", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await purge(db_state, book["uuid"])

    panel = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ADMIN)
    )
    view = await client.get(f"{VIEWS}/author/{author['uuid']}", headers={**roles(ADMIN), **INERTIA})
    assert panel.json()["total"] == 0
    assert view.json()["props"]["referrer_count"] == 0


async def test_the_panel_opens_for_a_trashed_record_an_editor_can_restore(client):
    """The editor renders the badge for a record in the trash; the panel
    behind it used to 404 on exactly the screen where "what still points at
    this?" decides whether to restore or purge."""
    from tests.relation_helpers import trash

    await make_type(client, "author", [field("name", "text")])
    await make_type(
        client, "book", [field("name", "text"), field("author", "relation", target_type="author")]
    )
    author = await make_record(client, "author", {"name": "A"})
    await make_record(
        client, "book", {"name": "B", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await trash(client.db_state, author["uuid"])

    panel = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ADMIN)
    )
    assert panel.status_code == 200
    assert panel.json()["total"] == 1

    # ``records.view`` alone cannot enumerate the trash, so the 404 stands.
    viewer = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ROLE_VIEWER)
    )
    assert viewer.status_code == 404
