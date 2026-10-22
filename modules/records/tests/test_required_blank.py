"""``required`` is not satisfied by an empty or whitespace-only string."""

from __future__ import annotations

from tests.app_harness import ADMIN, roles


def _field(key: str, type_: str, **overrides) -> dict:
    base = {"key": key, "type": type_, "label": key.title(), "indexed": True}
    base.update(overrides)
    return base


async def _make(client, key: str, fields: list[dict], **cols):
    return await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": fields, **cols},
        headers=roles(ADMIN),
    )


# --------------------------------------------------------------------------
# ``required`` is not satisfied by whitespace
# --------------------------------------------------------------------------


async def test_required_text_refuses_empty_and_blank(client):
    await _make(client, "req", [_field("a", "text", required=True)])
    for value in ("", "   ", "\t\n"):
        resp = await client.post(
            "/api/records/types/req/records",
            json={"data": {"a": value}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 422, repr(value)
        assert resp.json()["errors"][0]["field"] == "a"
    ok = await client.post(
        "/api/records/types/req/records", json={"data": {"a": "x"}}, headers=roles(ADMIN)
    )
    assert ok.status_code == 201


async def test_required_blank_rule_covers_every_string_shaped_type(client):
    choices = {"choices": [{"value": "a", "label": "A"}]}
    cases = {
        "longtext": {},
        "email": {},
        "url": {},
        "select": choices,
    }
    for kind, options in cases.items():
        await _make(
            client,
            f"rq_{kind}",
            [_field("a", kind, required=True, indexed=False, options=options)],
        )
        resp = await client.post(
            f"/api/records/types/rq_{kind}/records",
            json={"data": {"a": "  "}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 422, kind


async def test_an_optional_text_field_still_accepts_an_empty_string(client):
    """The rule is about ``required``, not about empty strings: an optional
    field may legitimately hold one, and so may an existing stored payload."""
    await _make(client, "opt", [_field("a", "text")])
    resp = await client.post(
        "/api/records/types/opt/records", json={"data": {"a": ""}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["a"] == ""
