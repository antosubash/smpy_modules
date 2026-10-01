"""The query grammar's caps: ``?filter=``, ``?sort=``, ``in:`` and ``?page=``.

Every input here used to reach SQL unbounded and come back as a ``500`` — on
the *anonymous* API, which needs no session at all: a hundred repeated
``?sort=`` terms was a hundred ``LEFT JOIN``s and SQLite's "at most 64 tables
in a join", two thousand ``in:`` values was "Expression tree is too large",
and ``?page=2**63`` was an ``OverflowError`` inside the driver.

So the assertions are all the same shape, and none of them is about a
message: **a refusal, never a crash**, and the same refusal on the admin
listing, on the anonymous one and on the export, because all three build the
plan through ``deps``' one grammar (`sm_records._grammar`).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.app_harness import ADMIN, roles

_API = "/api/records/types/post/records"
_PUBLIC = "/api/records/public/post"


def _field(key: str, *, indexed: bool = True) -> dict:
    return {"key": key, "type": "text", "label": key.title(), "indexed": indexed}


@pytest_asyncio.fixture
async def seeded(client):
    """One public type, three published records, and the public router
    mounted — so the same query can be asked with and without a session."""
    resp = await client.post(
        "/api/records/types",
        json={
            "key": "post",
            "label": "Post",
            "fields": [_field("title"), _field("body"), _field("tag")],
            "display_field": "title",
            "is_public": True,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    for i in range(3):
        await client.post(
            _API,
            json={"data": {"title": f"t{i}"}, "status": "published"},
            headers=roles(ADMIN),
        )
    await client.app.state.records_module.on_startup(client.app)
    return client


def _caps(client):
    return client.app.state.sm_records.settings


async def _get(client, url: str, query: str, *, anonymous: bool):
    headers = {} if anonymous else roles(ADMIN)
    return await client.get(f"{url}?{query}", headers=headers)


@pytest.mark.parametrize("anonymous", [False, True])
async def test_too_many_filter_terms_is_a_400_naming_the_parameter(seeded, anonymous):
    url = _PUBLIC if anonymous else _API
    cap = _caps(seeded).max_filter_terms
    ok = await _get(seeded, url, "&".join(["filter=title:contains:t"] * cap), anonymous=anonymous)
    assert ok.status_code == 200, ok.text
    refused = await _get(
        seeded, url, "&".join(["filter=title:contains:t"] * (cap + 1)), anonymous=anonymous
    )
    assert refused.status_code == 400, refused.text
    assert "filter" in refused.json()["detail"]


@pytest.mark.parametrize("anonymous", [False, True])
async def test_too_many_distinct_sort_terms_is_a_400(seeded, anonymous):
    url = _PUBLIC if anonymous else _API
    fields = ["title", "body", "tag", "slug", "display_title", "published_at", "created_at"]
    cap = _caps(seeded).max_sort_terms
    refused = await _get(
        seeded, url, "&".join(f"sort={name}" for name in fields[: cap + 1]), anonymous=anonymous
    )
    assert refused.status_code == 400, refused.text
    assert "sort" in refused.json()["detail"]


@pytest.mark.parametrize("anonymous", [False, True])
async def test_a_repeated_sort_term_is_one_term(seeded, anonymous):
    """A hundred ``sort=title`` is one join, not a hundred — the dedupe
    ``parse_expand`` has always done, so the cap bounds *ordering* rather than
    punishing a client that repeated itself."""
    url = _PUBLIC if anonymous else _API
    resp = await _get(seeded, url, "&".join(["sort=title"] * 100), anonymous=anonymous)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 3


@pytest.mark.parametrize("anonymous", [False, True])
async def test_an_oversized_in_list_is_a_400(seeded, anonymous):
    url = _PUBLIC if anonymous else _API
    cap = _caps(seeded).max_in_values
    ok = await _get(seeded, url, "filter=title:in:" + ",".join(["a"] * cap), anonymous=anonymous)
    assert ok.status_code == 200, ok.text
    refused = await _get(
        seeded, url, "filter=title:in:" + ",".join(["a"] * (cap + 1)), anonymous=anonymous
    )
    assert refused.status_code == 400, refused.text
    assert "filter" in refused.json()["detail"]


@pytest.mark.parametrize("anonymous", [False, True])
@pytest.mark.parametrize("page", [10**7, 10**19, 2**63])
async def test_an_unbounded_page_number_is_refused_not_a_500(seeded, anonymous, page):
    """``422`` and not ``400``: the bound is ``le=`` on the parameter, which
    is FastAPI's own validation — exactly what ``?page=0`` has always
    answered through the ``ge=1`` beside it. What matters is that the offset
    arithmetic never reaches the driver."""
    url = _PUBLIC if anonymous else _API
    resp = await _get(seeded, url, f"page={page}", anonymous=anonymous)
    assert resp.status_code == 422, resp.text


async def test_the_export_is_capped_by_the_same_grammar(seeded):
    """The export builds the list's plan from the same dependencies, so the
    caps are not something the download route can be walked around."""
    cap = _caps(seeded).max_filter_terms
    refused = await seeded.get(
        f"{_API}/export?" + "&".join(["filter=title:contains:t"] * (cap + 1)),
        headers=roles(ADMIN),
    )
    assert refused.status_code == 400, refused.text
    assert "filter" in refused.json()["detail"]
    assert "content-disposition" not in refused.headers

    sorts = "&".join(
        f"sort={name}" for name in ("title", "body", "tag", "slug", "created_at", "id")
    )
    assert (await seeded.get(f"{_API}/export?{sorts}", headers=roles(ADMIN))).status_code == 400


async def test_the_caps_are_settings(seeded):
    """Editable on the Settings screen like every other limit here — read per
    request, so lowering one takes effect without a restart."""
    _caps(seeded).max_filter_terms = 2
    refused = await seeded.get(
        f"{_API}?" + "&".join(["filter=title:contains:t"] * 3), headers=roles(ADMIN)
    )
    assert refused.status_code == 400, refused.text
    assert "at most 2" in refused.json()["detail"]
