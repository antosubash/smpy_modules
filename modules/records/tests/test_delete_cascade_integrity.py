"""A delete that reaches records the URL never names, and a refused one.

``allowed_roles`` is not bypassable through a cascade, a delete refused deeper
down commits nothing, and a relation payload must name the type its field
declares. Type keys are unique across the whole suite on purpose —
``schema.compile``'s model cache is process-global.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, api_record, api_type, roles
from tests.app_harness import field as _field

API = "/api/records"


def _ref(type_key: str, uuid: str) -> dict:
    return {"type": type_key, "uuid": uuid}


# --- allowed_roles is not bypassable through cascade/set_null -----------


async def test_cascade_into_a_restricted_type_is_refused_for_a_caller_without_its_roles(client):
    """``check_type_roles`` only ever sees the type in the URL, so a cascade
    used to trash records of a type the caller may not write at all."""
    await api_type(client, "f1open", [_field("name", "text")])
    await api_type(
        client,
        "f1secret",
        [_field("owner", "relation", target_type="f1open", on_delete="cascade")],
        allowed_roles=[ROLE_EDITOR_TWO],
    )
    target = await api_record(client, "f1open", {"name": "Public"})
    secret = await api_record(
        client, "f1secret", {"owner": _ref("f1open", target["uuid"])}, actor=ROLE_EDITOR_TWO
    )

    refused = await client.delete(
        f"{API}/types/f1open/records/{target['uuid']}", headers=roles(ROLE_EDITOR)
    )
    assert refused.status_code == 409
    # Counted, never named: the blocker lives in a type this caller may not
    # read, and the referrers panel refuses to name it for the same reason
    # (``contracts.relations``). The count is what has to stay honest.
    body = refused.json()
    assert body["referrers"] == []
    assert body["hidden"] == 1
    assert body["detail"].startswith("1 record(s) still reference")

    still_there = await client.get(
        f"{API}/types/f1secret/records/{secret['uuid']}", headers=roles(ROLE_EDITOR_TWO)
    )
    assert still_there.status_code == 200
    assert still_there.json()["is_deleted"] is False

    allowed = await client.delete(
        f"{API}/types/f1open/records/{target['uuid']}", headers=roles(ROLE_EDITOR_TWO)
    )
    assert allowed.status_code == 204
    gone = await client.get(
        f"{API}/types/f1secret/records/{secret['uuid']}", headers=roles(ROLE_EDITOR_TWO)
    )
    assert gone.status_code == 404


# --- a refused delete mutates nothing, and commits nothing --------------


async def test_a_delete_refused_deeper_down_leaves_the_set_null_referrer_alone(client):
    """Plan-then-apply, plus the explicit rollback in ``RecordsErrorRoute``.

    The set_null referrer is created *first* so it sorts ahead of the cascade
    one: the old code nulled it, then cascaded, then met the ``restrict`` and
    raised — and the 409 response committed the nulled payload.
    """
    await api_type(client, "f2target", [_field("name", "text")])
    await api_type(
        client,
        "f2loose",
        [_field("link", "relation", target_type="f2target", on_delete="set_null")],
    )
    await api_type(
        client,
        "f2chain",
        [_field("link", "relation", target_type="f2target", on_delete="cascade")],
    )
    await api_type(
        client,
        "f2holder",
        [_field("link", "relation", target_type="f2chain", on_delete="restrict")],
    )

    target = await api_record(client, "f2target", {"name": "Target"})
    loose = await api_record(client, "f2loose", {"link": _ref("f2target", target["uuid"])})
    chain = await api_record(client, "f2chain", {"link": _ref("f2target", target["uuid"])})
    await api_record(client, "f2holder", {"link": _ref("f2chain", chain["uuid"])})

    refused = await client.delete(
        f"{API}/types/f2target/records/{target['uuid']}", headers=roles(ADMIN)
    )
    assert refused.status_code == 409

    after = await client.get(f"{API}/types/f2loose/records/{loose['uuid']}", headers=roles(ADMIN))
    assert after.json()["data"]["link"] == _ref("f2target", target["uuid"])
    assert after.json()["version"] == 1
    # And the target itself is untouched, as are the two records downstream.
    assert (
        await client.get(f"{API}/types/f2target/records/{target['uuid']}", headers=roles(ADMIN))
    ).json()["is_deleted"] is False


# --- the payload's ``type`` must match the field's declared target ------


async def test_a_relation_payload_naming_another_type_is_refused_and_still_indexes(client):
    await api_type(client, "f3person", [_field("name", "text")])
    await api_type(
        client,
        "f3doc",
        [_field("author", "relation", target_type="f3person", on_delete="restrict")],
    )
    person = await api_record(client, "f3person", {"name": "Ada"})

    ghost = await client.post(
        f"{API}/types/f3doc/records",
        json={"data": {"author": {"type": "ghost", "uuid": person["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert ghost.status_code == 422
    assert [item["field"] for item in ghost.json()["errors"]] == ["author"]

    await api_record(client, "f3doc", {"author": _ref("f3person", person["uuid"])})
    blocked = await client.delete(
        f"{API}/types/f3person/records/{person['uuid']}", headers=roles(ADMIN)
    )
    assert blocked.status_code == 409
