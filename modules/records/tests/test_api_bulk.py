"""``POST /types/{key}/records/bulk`` — the five actions and the one semantic.

The semantic is all-or-nothing, and it is what most of this file is about: a
batch that cannot apply to every record it names applies to none of them, and
says which ones refused and why. Everything else follows from the service
composing the single-record calls — the cascade, the claims, the revisions
and the events are those calls', not a second implementation, and the tests
that matter for them are the ones that prove the composition rather than
re-proving their behaviour.
"""

from __future__ import annotations

import pytest_asyncio

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, ROLE_VIEWER, roles
from tests.bulk_helpers import API, BULK, bulk, make_product, make_records, read, trash_listing


@pytest_asyncio.fixture
async def product(client) -> dict:
    return await make_product(client)


async def test_bulk_trash_moves_every_named_record(client, product):
    uuids = await make_records(client, 3)

    resp = await bulk(client, "trash", uuids)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"action": "trash", "requested": 3, "changed": 3, "cascaded": 0}
    for uuid in uuids:
        assert (await read(client, uuid)).status_code == 404
    assert (await trash_listing(client))["total"] == 3


async def test_bulk_restore_brings_them_back(client, product):
    uuids = await make_records(client, 3)
    assert (await bulk(client, "trash", uuids)).status_code == 200

    resp = await bulk(client, "restore", uuids)

    assert resp.status_code == 200, resp.text
    assert resp.json()["changed"] == 3
    for uuid in uuids:
        body = (await read(client, uuid)).json()
        assert body["is_deleted"] is False


async def test_bulk_purge_only_takes_trashed_records(client, product):
    uuids = await make_records(client, 2)

    live = await bulk(client, "purge", uuids)

    # ``hard_delete_record`` refuses anything not already in the trash, on
    # purpose — a purge is unrecoverable and reaching it in one step from a
    # live record turns a mis-click into permanent data loss. The report
    # carries that same 409, per uuid.
    assert live.status_code == 409
    failed = live.json()["report"]["failed"]
    assert [entry["status"] for entry in failed] == [409, 409]
    assert "must be in the trash" in failed[0]["message"]

    assert (await bulk(client, "trash", uuids)).status_code == 200
    purged = await bulk(client, "purge", uuids)
    assert purged.status_code == 200, purged.text
    assert purged.json()["changed"] == 2
    assert (await trash_listing(client))["total"] == 0


async def test_bulk_publish_and_unpublish_bump_the_version(client, product):
    uuids = await make_records(client, 2)
    before = [(await read(client, uuid)).json() for uuid in uuids]
    assert [row["status"] for row in before] == ["draft", "draft"]

    published = await bulk(client, "publish", uuids)
    assert published.status_code == 200, published.text
    assert published.json() == {
        "action": "publish",
        "requested": 2,
        "changed": 2,
        "cascaded": 0,
    }

    after = [(await read(client, uuid)).json() for uuid in uuids]
    assert [row["status"] for row in after] == ["published", "published"]
    assert [row["version"] for row in after] == [row["version"] + 1 for row in before]
    assert all(row["published_at"] for row in after)

    back = await bulk(client, "unpublish", uuids)
    assert back.status_code == 200, back.text
    final = [(await read(client, uuid)).json() for uuid in uuids]
    assert [row["status"] for row in final] == ["draft", "draft"]
    # Unpublishing clears the stamp, exactly as ``PUT`` does (``_published_at``).
    assert [row["published_at"] for row in final] == [None, None]


async def test_publish_keeps_a_hand_set_slug(client, product):
    """The action changes one thing. A status-only write that re-derived the
    slug from the payload would silently rename a record's public URL."""
    created = await client.post(
        API,
        json={"data": {"name": "Item 0", "topic": "news"}, "slug": "chosen-by-hand"},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]

    assert (await bulk(client, "publish", [uuid])).status_code == 200

    assert (await read(client, uuid)).json()["slug"] == "chosen-by-hand"


async def test_a_repeated_uuid_counts_once(client, product):
    """A selection model that sends the same record twice means it once — and
    the second turn would otherwise refuse and take the batch with it."""
    uuids = await make_records(client, 1)

    resp = await bulk(client, "trash", [uuids[0], uuids[0]])

    assert resp.status_code == 200, resp.text
    assert resp.json()["requested"] == 1
    assert resp.json()["changed"] == 1


# --- the refusal report ----------------------------------------------------


async def test_one_bad_uuid_refuses_the_whole_batch_and_names_it(client, product):
    uuids = await make_records(client, 3)
    missing = "f" * 32

    resp = await bulk(client, "trash", [uuids[0], missing, uuids[1]])

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["report"]["action"] == "trash"
    assert body["report"]["requested"] == 3
    assert [entry["uuid"] for entry in body["report"]["failed"]] == [missing]
    assert body["report"]["failed"][0]["status"] == 404
    assert "1 of 3" in body["detail"]
    assert "nothing was changed" in body["detail"]
    # The whole point: the two records that *could* have been trashed were not.
    for uuid in uuids[:2]:
        assert (await read(client, uuid)).json()["is_deleted"] is False
    assert (await trash_listing(client))["total"] == 0


async def test_a_stale_expected_version_refuses_the_batch(client, product):
    uuids = await make_records(client, 2)
    current = (await read(client, uuids[1])).json()["version"]

    resp = await bulk(
        client,
        "trash",
        uuids,
        expected_versions={uuids[1]: current + 5},
    )

    assert resp.status_code == 409, resp.text
    failed = resp.json()["report"]["failed"]
    assert [entry["uuid"] for entry in failed] == [uuids[1]]
    assert failed[0]["status"] == 409
    assert "has changed since it was read" in failed[0]["message"]
    assert (await trash_listing(client))["total"] == 0


async def test_a_matching_expected_version_is_applied(client, product):
    uuids = await make_records(client, 2)
    versions = {uuid: (await read(client, uuid)).json()["version"] for uuid in uuids}

    resp = await bulk(client, "trash", uuids, expected_versions=versions)

    assert resp.status_code == 200, resp.text
    assert (await trash_listing(client))["total"] == 2


async def test_every_failing_uuid_is_reported_not_only_the_first(client, product):
    """The pass does not stop at the first refusal — a report naming one of
    three is a report the operator has to discover the rest of by retrying."""
    uuids = await make_records(client, 3)
    missing = ["a" * 32, "b" * 32]

    resp = await bulk(client, "trash", [missing[0], uuids[0], missing[1]])

    failed = resp.json()["report"]["failed"]
    assert [entry["uuid"] for entry in failed] == missing


# --- permissions -----------------------------------------------------------


async def test_bulk_needs_records_edit(client, product):
    uuids = await make_records(client, 1)
    resp = await bulk(client, "trash", uuids, actor=ROLE_VIEWER)
    assert resp.status_code == 403


async def test_allowed_roles_narrow_the_batch(client):
    await make_product(client, allowed_roles=[ROLE_EDITOR])
    uuids = await make_records(client, 2, actor=ROLE_EDITOR)

    refused = await bulk(client, "trash", uuids, actor=ROLE_EDITOR_TWO)
    assert refused.status_code == 403

    allowed = await bulk(client, "trash", uuids, actor=ROLE_EDITOR)
    assert allowed.status_code == 200, allowed.text


async def test_an_anonymous_caller_is_refused(client, product):
    resp = await client.post(BULK, json={"action": "trash", "uuids": ["x" * 32]})
    assert resp.status_code in (401, 403)


# --- the ceiling and the body ----------------------------------------------


async def test_more_uuids_than_max_bulk_records_is_a_413(client, product):
    uuids = await make_records(client, 2)
    client.app.state.sm_records.settings.max_bulk_records = 1

    resp = await bulk(client, "trash", uuids)

    assert resp.status_code == 413, resp.text
    assert "over the 1-record limit" in resp.json()["detail"]
    # Refused before a record was touched.
    assert (await trash_listing(client))["total"] == 0


async def test_the_ceiling_admits_a_batch_exactly_at_it(client, product):
    uuids = await make_records(client, 2)
    client.app.state.sm_records.settings.max_bulk_records = 2

    assert (await bulk(client, "trash", uuids)).status_code == 200


async def test_an_empty_uuid_list_is_a_422(client, product):
    resp = await client.post(BULK, json={"action": "trash", "uuids": []}, headers=roles(ADMIN))
    assert resp.status_code == 422


async def test_an_unknown_action_is_a_422(client, product):
    uuids = await make_records(client, 1)
    resp = await bulk(client, "archive", uuids)
    assert resp.status_code == 422
