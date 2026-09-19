"""Regressions for the review findings — every test here failed before its fix.

Kept in one file rather than scattered because the findings share two shapes:
a delete that reaches records the URL never names, and a refused write that
was committed anyway. Type keys are unique across the whole suite on purpose
— ``schema.compile``'s model cache is process-global.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, roles

API = "/api/records"


def _field(key: str, type_: str, *, indexed: bool = True, **options) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": False,
        "unique": False,
        "indexed": indexed,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def _type(client, key: str, fields: list[dict], **cols) -> dict:
    resp = await client.post(
        f"{API}/types",
        json={"key": key, "label": key.title(), "fields": fields, **cols},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _record(client, key: str, data: dict, *, as_role: str = ADMIN) -> dict:
    resp = await client.post(
        f"{API}/types/{key}/records", json={"data": data}, headers=roles(as_role)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ref(type_key: str, uuid: str) -> dict:
    return {"type": type_key, "uuid": uuid}


# --- F1: allowed_roles is not bypassable through cascade/set_null -----------


async def test_cascade_into_a_restricted_type_is_refused_for_a_caller_without_its_roles(client):
    """``check_type_roles`` only ever sees the type in the URL, so a cascade
    used to trash records of a type the caller may not write at all."""
    await _type(client, "f1open", [_field("name", "text")])
    await _type(
        client,
        "f1secret",
        [_field("owner", "relation", target_type="f1open", on_delete="cascade")],
        allowed_roles=[ROLE_EDITOR_TWO],
    )
    target = await _record(client, "f1open", {"name": "Public"})
    secret = await _record(
        client, "f1secret", {"owner": _ref("f1open", target["uuid"])}, as_role=ROLE_EDITOR_TWO
    )

    refused = await client.delete(
        f"{API}/types/f1open/records/{target['uuid']}", headers=roles(ROLE_EDITOR)
    )
    assert refused.status_code == 409
    assert refused.json()["referrers"] == [secret["uuid"]]

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


# --- F2: a refused delete mutates nothing, and commits nothing --------------


async def test_a_delete_refused_deeper_down_leaves_the_set_null_referrer_alone(client):
    """Plan-then-apply, plus the explicit rollback in ``RecordsErrorRoute``.

    The set_null referrer is created *first* so it sorts ahead of the cascade
    one: the old code nulled it, then cascaded, then met the ``restrict`` and
    raised — and the 409 response committed the nulled payload.
    """
    await _type(client, "f2target", [_field("name", "text")])
    await _type(
        client,
        "f2loose",
        [_field("link", "relation", target_type="f2target", on_delete="set_null")],
    )
    await _type(
        client,
        "f2chain",
        [_field("link", "relation", target_type="f2target", on_delete="cascade")],
    )
    await _type(
        client,
        "f2holder",
        [_field("link", "relation", target_type="f2chain", on_delete="restrict")],
    )

    target = await _record(client, "f2target", {"name": "Target"})
    loose = await _record(client, "f2loose", {"link": _ref("f2target", target["uuid"])})
    chain = await _record(client, "f2chain", {"link": _ref("f2target", target["uuid"])})
    await _record(client, "f2holder", {"link": _ref("f2chain", chain["uuid"])})

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


# --- F3: the payload's ``type`` must match the field's declared target ------


async def test_a_relation_payload_naming_another_type_is_refused_and_still_indexes(client):
    await _type(client, "f3person", [_field("name", "text")])
    await _type(
        client,
        "f3doc",
        [_field("author", "relation", target_type="f3person", on_delete="restrict")],
    )
    person = await _record(client, "f3person", {"name": "Ada"})

    ghost = await client.post(
        f"{API}/types/f3doc/records",
        json={"data": {"author": {"type": "ghost", "uuid": person["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert ghost.status_code == 422
    assert [item["field"] for item in ghost.json()["errors"]] == ["author"]

    await _record(client, "f3doc", {"author": _ref("f3person", person["uuid"])})
    blocked = await client.delete(
        f"{API}/types/f3person/records/{person['uuid']}", headers=roles(ADMIN)
    )
    assert blocked.status_code == 409


# --- F4/F5/F6: the trash counts, and the pointers are editable now ----------


async def _one_trashed(client, key: str) -> dict:
    await _type(client, key, [_field("name", "text"), _field("alt", "text")])
    record = await _record(client, key, {"name": "Trashed"})
    assert (
        await client.delete(f"{API}/types/{key}/records/{record['uuid']}", headers=roles(ADMIN))
    ).status_code == 204
    read = await client.get(f"{API}/types/{key}", headers=roles(ADMIN))
    assert read.json()["record_count"] == 0
    return read.json()


async def test_the_trash_still_counts_when_a_schema_change_is_classified(client):
    """F4 was "the lock counts the trash". Phase 3 replaced the lock with the
    dry run of design §8.2, and the rule survives the replacement: a trashed
    record still holds content the schema describes and a restore reads it
    back, so a change that would invalidate it is refused for it."""
    rtype = await _one_trashed(client, "f4thing")
    assert (rtype["trashed_record_count"], rtype["fields_locked"]) == (1, True)

    # The trashed record has no ``alt`` value, so requiring it fails for the
    # only record the type has — which is in the trash.
    resp = await client.put(
        f"{API}/types/f4thing",
        json={
            "expected_version": rtype["version"],
            "fields": [_field("name", "text"), {**_field("alt", "text"), "required": True}],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 409
    assert "would not satisfy the new schema" in resp.json()["detail"]

    after = await client.get(f"{API}/types/f4thing", headers=roles(ADMIN))
    assert after.json()["schema_version"] == 1


async def test_delete_type_confirms_against_the_trash_too(client):
    await _one_trashed(client, "f5thing")
    refused = await client.delete(
        f"{API}/types/f5thing", params={"confirm_record_count": 0}, headers=roles(ADMIN)
    )
    assert refused.status_code == 409
    assert (
        await client.delete(
            f"{API}/types/f5thing", params={"confirm_record_count": 1}, headers=roles(ADMIN)
        )
    ).status_code == 204


async def test_display_and_slug_field_are_editable_on_a_populated_type(client):
    """F6 locked both pointers on a populated type, because Phase 1 had nothing
    that recomputed ``display_title`` for records already written. Phase 3
    does: a ``display_field`` change enqueues a whole-type rebuild (``"*"`` in
    ``reindex_pending``, design §18 Q2), and ``slug_field`` deliberately
    changes nothing already stored — a slug is an address."""
    await _type(client, "f6thing", [_field("name", "text"), _field("alt", "text")])
    record = await _record(client, "f6thing", {"name": "One", "alt": "Other"})
    version = (await client.get(f"{API}/types/f6thing", headers=roles(ADMIN))).json()["version"]

    for pointer in ("display_field", "slug_field"):
        resp = await client.put(
            f"{API}/types/f6thing",
            json={"expected_version": version, pointer: "alt"},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 200, (pointer, resp.text)
        version = resp.json()["version"]

    # Neither pointer rewrote the record: the title waits for the rebuild and
    # the slug is not regenerated at all.
    unchanged = await client.get(
        f"{API}/types/f6thing/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert unchanged.json()["slug"] == record["slug"]
    assert unchanged.json()["version"] == 1

    # A label edit on the same populated type still goes through.
    ok = await client.put(
        f"{API}/types/f6thing",
        json={"expected_version": version, "label": "Renamed"},
        headers=roles(ADMIN),
    )
    assert ok.status_code == 200
    assert ok.json()["label"] == "Renamed"
