"""The record list *screen* paging by keyset — ``?after=`` on the Inertia view.

Past ``RecordsSettings.max_count`` the total is the cap and the numbered pager
stops at the cap's last page; the rows beyond it used to be reachable only
through the JSON API. The view now takes the API's own cursor, so these tests
walk a type with more rows than the cap *through the view*, and pin what the
screen does with every cursor the service refuses: the list's notice, never
an error status (a page navigation that 400s is an Inertia modal).
"""

from __future__ import annotations

import pytest
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles
from tests.app_harness import field as _field

_API = "/api/records/types"
_VIEW = "/admin/records/widget"
_HEADERS = {**roles(ADMIN), "X-Inertia": "true", "X-Inertia-Version": "1.0"}
_ROWS = 11
_CAP = 4


async def _seed(client, count: int = _ROWS) -> list[str]:
    body = {"key": "widget", "label": "Widget", "fields": [_field("name")], "display_field": "name"}
    made = await client.post(_API, json=body, headers=roles(ADMIN))
    assert made.status_code == 201, made.text
    titles = [f"item-{n:03d}" for n in range(count)]
    # Created out of name order, so a walk that came back in insertion (id)
    # order would not pass for one in ``name`` order by accident.
    for title in reversed(titles):
        row = await client.post(
            f"{_API}/widget/records", json={"data": {"name": title}}, headers=roles(ADMIN)
        )
        assert row.status_code == 201, row.text
    client.app.state.sm_records.settings = RecordsSettings(max_count=_CAP)
    return titles


async def _page(client, query: str) -> dict:
    resp = await client.get(f"{_VIEW}?{query}", headers=_HEADERS)
    # Never an error status, whatever the query: see the module docstring.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["component"] == "Records/RecordList"
    return body["props"]


async def _walk(client, base: str) -> tuple[list[str], list[dict]]:
    """The footer's own route: numbered pages up to the cap's last page, then
    ``after=next_cursor`` until a page carries none."""
    seen: list[str] = []
    pages: list[dict] = []
    props = await _page(client, base)
    records = props["records"]
    last_numbered = -(-records["total"] // records["page_size"])
    for number in range(2, last_numbered + 1):
        pages.append(records)
        seen += [item["display_title"] for item in records["items"]]
        records = (await _page(client, f"{base}&page={number}"))["records"]
    for _ in range(3 * _ROWS):
        pages.append(records)
        seen += [item["display_title"] for item in records["items"]]
        if records["next_cursor"] is None:
            break
        props = await _page(client, f"{base}&after={records['next_cursor']}")
        assert props["list_errors"] == {}
        records = props["records"]
    return seen, pages


@pytest.mark.parametrize("sort", ["name", "-name"])
async def test_after_walks_every_record_past_the_cap_in_sort_order(client, sort):
    titles = await _seed(client)
    seen, pages = await _walk(client, f"sort={sort}&page_size=3")
    expected = sorted(titles, reverse=sort.startswith("-"))
    # Every record, in order, once: no gap where the numbered pages hand over
    # to the cursor and none between two cursor pages.
    assert seen == expected
    assert len(set(seen)) == _ROWS
    # The capped count is still what every page reports…
    assert all((p["total"], p["total_capped"]) == (_CAP, True) for p in pages)
    # …and a page reached by cursor has no number: it is past the numbered
    # pages, and a "Page 2" there would be a false one.
    numbered = [p["page"] for p in pages if p["page"] is not None]
    assert numbered == [1, 2]
    assert all(p["page"] is None for p in pages[2:])


async def test_after_walks_the_default_sort_too(client):
    """No ``?sort=``: the view's default (``position``, then ``updated_at``
    descending) is what the cursor is bound to — a datetime key, which is
    where a cursor that does not round-trip its own values shows up."""
    titles = await _seed(client)
    seen, _ = await _walk(client, "page_size=3")
    assert sorted(seen) == titles
    assert len(seen) == _ROWS


async def test_the_apis_cursor_resumes_the_screen(client):
    """The same opaque cursor: one minted by ``GET …/records`` with an
    explicit sort continues the view under that sort."""
    titles = await _seed(client)
    api = await client.get(f"{_API}/widget/records?sort=name&page_size=5", headers=roles(ADMIN))
    cursor = api.json()["next_cursor"]
    props = await _page(client, f"sort=name&page_size=5&after={cursor}")
    assert [item["display_title"] for item in props["records"]["items"]] == titles[5:10]


async def test_a_tampered_cursor_is_the_lists_notice(client):
    await _seed(client)
    first = (await _page(client, "sort=name&page_size=3"))["records"]
    tampered = first["next_cursor"][:-4] + "AAAA"
    props = await _page(client, f"sort=name&page_size=3&after={tampered}")
    assert props["list_errors"] == {"filter": "bad_cursor"}
    assert props["records"]["items"] == []
    assert (props["records"]["page"], props["records"]["next_cursor"]) == (None, None)

    garbage = await _page(client, "sort=name&after=not-a-cursor")
    assert garbage["list_errors"] == {"filter": "bad_cursor"}


async def test_a_cursor_under_another_sort_is_refused(client):
    await _seed(client)
    first = (await _page(client, "sort=name&page_size=3"))["records"]
    props = await _page(client, f"sort=-name&page_size=3&after={first['next_cursor']}")
    assert props["list_errors"] == {"filter": "bad_cursor"}
    assert props["records"]["items"] == []


async def test_a_live_cursor_in_the_trash_is_refused(client):
    """``trashed`` is part of the cursor's signature: the trash and the live
    list are two orders, even when they sort by the same field."""
    await _seed(client)
    first = (await _page(client, "sort=name&page_size=3"))["records"]
    props = await _page(client, f"sort=name&page_size=3&trashed=true&after={first['next_cursor']}")
    assert props["list_errors"] == {"filter": "bad_cursor"}


async def test_page_and_after_together_are_refused(client):
    """Refused, as on the API (``deps.parse_cursor``) — never resolved in
    favour of one. The footer never writes both; a URL carrying both was
    edited by hand and has no single right answer."""
    await _seed(client)
    first = (await _page(client, "sort=name&page_size=3"))["records"]
    props = await _page(client, f"sort=name&page_size=3&page=2&after={first['next_cursor']}")
    assert props["list_errors"] == {"filter": "page_and_after"}
    assert props["records"]["items"] == []
    # ``page=1`` is the parameter's default and means "no page was asked
    # for", exactly as the API reads it.
    ok = await _page(client, f"sort=name&page_size=3&page=1&after={first['next_cursor']}")
    assert ok["list_errors"] == {}
    assert len(ok["records"]["items"]) == 3


async def test_an_empty_after_is_offset_paging(client):
    await _seed(client)
    props = await _page(client, "sort=name&page_size=3&page=2&after=")
    assert props["list_errors"] == {}
    assert props["records"]["page"] == 2
    assert [item["display_title"] for item in props["records"]["items"]] == [
        "item-003",
        "item-004",
        "item-005",
    ]


async def test_a_malformed_filter_still_wins_over_the_cursor(client):
    """A filter that does not parse is reported as that, not as the cursor
    it arrived with — the filter is the thing the notice has to name."""
    await _seed(client)
    first = (await _page(client, "sort=name&page_size=3"))["records"]
    props = await _page(client, f"sort=name&filter=nonsense&after={first['next_cursor']}")
    assert props["list_errors"] == {"filter": "malformed"}
