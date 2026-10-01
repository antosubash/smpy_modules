"""POLISH 2: `GET /types/{key}/revisions` is paged.

Type revisions are never pruned — they are what a rollback reads, so a cap
would eventually delete the version somebody wants back — which means the
*response* is what has to be bounded. Unpaged it grew for the lifetime of the
type and was re-downloaded on every open of the schema screen: measured, 31
revisions of a four-field type is 24 KB, ~780 B each, so a sixty-field type
edited a few hundred times is a multi-MB payload per open.

Only *schema* changes append a revision (a description-only `PUT` does not),
which is why every edit below moves a field.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"


def _field(key: str) -> dict:
    return {"key": key, "type": "text", "label": key.title(), "indexed": True}


async def _type_with_history(client, key: str, edits: int) -> None:
    """One type, plus ``edits`` schema changes — ``edits + 1`` revisions."""
    resp = await client.post(
        _API,
        json={
            "key": key,
            "label": key.title(),
            "fields": [_field("name")],
            "display_field": "name",
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()["version"]
    for index in range(edits):
        edit = await client.put(
            f"{_API}/{key}",
            json={
                "fields": [_field("name"), *(_field(f"extra{n}") for n in range(index + 1))],
                "expected_version": version,
            },
            headers=roles(ADMIN),
        )
        assert edit.status_code == 200, edit.text
        version = edit.json()["version"]


async def _revisions(client, key: str, **params):
    query = "".join(f"&{name}={value}" for name, value in params.items())
    return await client.get(f"{_API}/{key}/revisions?{query}", headers=roles(ADMIN))


async def test_the_response_carries_the_page_and_the_exact_total(client):
    await _type_with_history(client, "revpage", edits=4)
    resp = await _revisions(client, "revpage", page_size=2)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2


async def test_pages_walk_the_history_newest_first_without_gaps(client):
    await _type_with_history(client, "revwalk", edits=4)
    seen: list[int] = []
    for page in (1, 2, 3):
        resp = await _revisions(client, "revwalk", page=page, page_size=2)
        assert resp.status_code == 200, resp.text
        seen.extend(item["id"] for item in resp.json()["items"])
    assert len(seen) == 5
    assert seen == sorted(seen, reverse=True), "newest first"
    assert len(set(seen)) == 5, "a row appeared on two pages"


async def test_a_page_past_the_end_is_an_empty_page_not_an_error(client):
    await _type_with_history(client, "revend", edits=1)
    resp = await _revisions(client, "revend", page=99, page_size=2)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 2


async def test_page_size_is_clamped_like_every_other_listing(client):
    await _type_with_history(client, "revclamp", edits=1)
    settings = client.app.state.sm_records.settings
    resp = await _revisions(client, "revclamp", page_size=settings.max_page_size + 500)
    assert resp.status_code == 200, resp.text
    assert resp.json()["page_size"] == settings.max_page_size


async def test_the_default_page_size_applies_when_none_is_sent(client):
    await _type_with_history(client, "revdefault", edits=1)
    settings = client.app.state.sm_records.settings
    resp = await _revisions(client, "revdefault")
    assert resp.status_code == 200, resp.text
    assert resp.json()["page_size"] == settings.default_page_size
