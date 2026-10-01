"""The bounded total, the keyset cursor and the prefix search — F4, F9, F11.

Three perf findings whose fixes are all *contracts*, not just faster SQL, so
they need tests that say what the contract is rather than how fast it runs
(the perf suite says that, and asserts no wall-clock thresholds).
"""

from __future__ import annotations

from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles
from tests.app_harness import field as _field

_API = "/api/records/types"


async def _seed(client, count: int, *, key: str = "widget") -> None:
    body = {
        "key": key,
        "label": key.title(),
        "fields": [_field("name", "text")],
        "display_field": "name",
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    for n in range(count):
        made = await client.post(
            f"{_API}/{key}/records",
            json={"data": {"name": f"item-{n:03d}"}},
            headers=roles(ADMIN),
        )
        assert made.status_code == 201, made.text


def _settings(client, **overrides) -> None:
    client.app.state.sm_records.settings = RecordsSettings(**overrides)


async def test_total_is_exact_below_the_cap(client):
    await _seed(client, 4)
    _settings(client, max_count=10)
    body = (await client.get(f"{_API}/widget/records", headers=roles(ADMIN))).json()
    assert (body["total"], body["total_capped"]) == (4, False)


async def test_total_is_capped_above_it(client):
    await _seed(client, 5)
    _settings(client, max_count=3)
    body = (await client.get(f"{_API}/widget/records", headers=roles(ADMIN))).json()
    # Exactly the cap, and the flag — never the real number, which is the
    # whole point of not counting past ``cap + 1``.
    assert (body["total"], body["total_capped"]) == (3, True)


async def test_the_cap_counts_matches_not_rows(client):
    """The bound is applied to the *filtered* set, so a filter narrowing the
    type below the cap gets an exact total again."""
    await _seed(client, 5)
    _settings(client, max_count=3)
    body = (
        await client.get(f"{_API}/widget/records?filter=name:eq:item-002", headers=roles(ADMIN))
    ).json()
    assert (body["total"], body["total_capped"]) == (1, False)


async def test_total_false_skips_the_count(client):
    await _seed(client, 3)
    body = (await client.get(f"{_API}/widget/records?total=false", headers=roles(ADMIN))).json()
    assert (body["total"], body["total_capped"]) == (None, False)
    assert len(body["items"]) == 3


async def test_cursor_walks_the_whole_type_without_offset(client):
    await _seed(client, 7)
    seen: list[str] = []
    url = f"{_API}/widget/records?page_size=2&sort=name&total=false"
    for _ in range(10):
        body = (await client.get(url, headers=roles(ADMIN))).json()
        seen += [item["display_title"] for item in body["items"]]
        if body["next_cursor"] is None:
            break
        url = f"{_API}/widget/records?page_size=2&sort=name&total=false&after={body['next_cursor']}"
    assert seen == [f"item-{n:03d}" for n in range(7)]


async def test_cursor_agrees_with_offset_paging(client):
    await _seed(client, 6)
    first = (
        await client.get(f"{_API}/widget/records?page_size=2&sort=-name", headers=roles(ADMIN))
    ).json()
    by_cursor = (
        await client.get(
            f"{_API}/widget/records?page_size=2&sort=-name&after={first['next_cursor']}",
            headers=roles(ADMIN),
        )
    ).json()
    by_page = (
        await client.get(
            f"{_API}/widget/records?page_size=2&sort=-name&page=2", headers=roles(ADMIN)
        )
    ).json()
    assert [i["uuid"] for i in by_cursor["items"]] == [i["uuid"] for i in by_page["items"]]


async def test_a_cursor_from_another_sort_is_refused(client):
    await _seed(client, 4)
    body = (
        await client.get(f"{_API}/widget/records?page_size=2&sort=name", headers=roles(ADMIN))
    ).json()
    refused = await client.get(
        f"{_API}/widget/records?page_size=2&sort=-name&after={body['next_cursor']}",
        headers=roles(ADMIN),
    )
    assert refused.status_code == 400


async def test_a_malformed_cursor_is_refused(client):
    await _seed(client, 2)
    refused = await client.get(f"{_API}/widget/records?after=not-a-cursor", headers=roles(ADMIN))
    assert refused.status_code == 400


async def test_page_and_after_together_are_refused(client):
    await _seed(client, 2)
    refused = await client.get(f"{_API}/widget/records?page=2&after=x", headers=roles(ADMIN))
    assert refused.status_code == 400


async def test_the_last_page_carries_no_cursor(client):
    await _seed(client, 3)
    body = (
        await client.get(f"{_API}/widget/records?page_size=10&sort=name", headers=roles(ADMIN))
    ).json()
    assert body["next_cursor"] is None


async def test_starts_with_on_display_title(client):
    await _seed(client, 3)
    body = (
        await client.get(
            f"{_API}/widget/records?filter=display_title:starts_with:item-00", headers=roles(ADMIN)
        )
    ).json()
    assert len(body["items"]) == 3
    none = (
        await client.get(
            f"{_API}/widget/records?filter=display_title:starts_with:tem", headers=roles(ADMIN)
        )
    ).json()
    # A prefix and not a substring: "tem" is inside every title and starts none.
    assert none["items"] == []


async def test_starts_with_on_an_indexed_text_field(client):
    await _seed(client, 3)
    body = (
        await client.get(
            f"{_API}/widget/records?filter=name:starts_with:item-00", headers=roles(ADMIN)
        )
    ).json()
    assert len(body["items"]) == 3


async def test_starts_with_is_a_range_and_case_sensitive(client):
    """``starts_with`` is ``low <= col < successor`` and therefore exact,
    case-sensitive and index-servable — ``contains`` is the forgiving one."""
    await _seed(client, 2)
    hit = (
        await client.get(
            f"{_API}/widget/records?filter=display_title:starts_with:item", headers=roles(ADMIN)
        )
    ).json()
    assert len(hit["items"]) == 2
    miss = (
        await client.get(
            f"{_API}/widget/records?filter=display_title:starts_with:ITEM", headers=roles(ADMIN)
        )
    ).json()
    assert miss["items"] == []
    # The upper bound is tight: "item-000" must not fall out of ["item", "iten").
    edge = (
        await client.get(
            f"{_API}/widget/records?filter=display_title:starts_with:item-000",
            headers=roles(ADMIN),
        )
    ).json()
    assert len(edge["items"]) == 1


async def test_starts_with_is_refused_on_a_non_text_column(client):
    await _seed(client, 1)
    refused = await client.get(
        f"{_API}/widget/records?filter=position:starts_with:1", headers=roles(ADMIN)
    )
    assert refused.status_code == 400


async def _trash(client, uuids: list[str]) -> None:
    for uuid in uuids:
        gone = await client.delete(f"{_API}/widget/records/{uuid}", headers=roles(ADMIN))
        assert gone.status_code == 204, gone.text


async def test_the_bound_does_not_fill_with_trashed_rows(client):
    """The subtle half of the bounded count: the soft-delete filter has to be
    inside the ``LIMIT``, not only outside it. With six rows, three trashed
    and a cap of three, a bound that limited *before* hiding the trash would
    report fewer than the three live ones."""
    await _seed(client, 6)
    listed = (await client.get(f"{_API}/widget/records?page_size=6", headers=roles(ADMIN))).json()
    # Trash the first three, which are also the first three the inner LIMIT
    # would meet in id order.
    await _trash(client, [item["uuid"] for item in listed["items"]][:3])
    _settings(client, max_count=3)
    body = (await client.get(f"{_API}/widget/records", headers=roles(ADMIN))).json()
    assert (body["total"], body["total_capped"]) == (3, False)
    assert len(body["items"]) == 3


async def test_the_trash_listing_is_capped_too(client):
    await _seed(client, 5)
    listed = (await client.get(f"{_API}/widget/records?page_size=5", headers=roles(ADMIN))).json()
    await _trash(client, [item["uuid"] for item in listed["items"]][:4])
    _settings(client, max_count=2)
    body = (await client.get(f"{_API}/widget/records?trashed=true", headers=roles(ADMIN))).json()
    assert (body["total"], body["total_capped"]) == (2, True)


def test_prefix_range_is_tight_and_total():
    """``_prefix.prefix_range`` is the whole of ``starts_with``: the
    range must contain every string beginning with the term and nothing
    else, including at the ends of the code-point space."""
    from sm_records.index._prefix import prefix_range

    low, high = prefix_range("ab")
    assert (low, high) == ("ab", "ac")
    for inside in ("ab", "abz", "ab\U0010ffff"):
        assert low <= inside < high
    for outside in ("aa", "aazzz", "ac", "b"):
        assert not (low <= outside < high)
    # A surrogate is not a legal code point, so the successor steps over the
    # whole block rather than producing an unencodable string.
    assert prefix_range("a\ud7ff")[1] == "a\ue000"
    # Nothing sorts after the maximum code point, so there is no upper bound.
    assert prefix_range("\U0010ffff") == ("\U0010ffff", None)
