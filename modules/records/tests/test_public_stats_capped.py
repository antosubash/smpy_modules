"""The anonymous stats are bounded the way the listing's ``total`` is (#88).

Without the bound an anonymous caller could ask for a ``count(distinct)`` or a
``sum`` over every published row of the biggest public type, under any filter
the allow-list takes, as often as it liked — the cost ``max_count`` exists to
cap on the listing. So a count stops at ``max_count`` and says so, and a sum
that would have to read more than ``max_count`` records answers ``null``
rather than a number that is not the sum.
"""

from __future__ import annotations

import pytest_asyncio

from tests.app_harness import ADMIN, api_record, api_type, field, roles
from tests.isolation_support import PUBLIC

_KEY = "plot"
_STATS = f"{PUBLIC}/{_KEY}/stats"
_CAP = 3


@pytest_asyncio.fixture
async def plots(public_client):
    state = public_client.app.state.sm_records
    state.settings = state.settings.model_copy(update={"max_count": _CAP})
    await api_type(
        public_client,
        _KEY,
        [field("name"), field("area", "number"), field("kind")],
        display_field="name",
        is_public=True,
    )
    return public_client


async def _seed(client, count: int, *, kind: str = "a") -> None:
    for n in range(count):
        data = {"name": f"{kind}-{n}", "area": 2, "kind": kind}
        await api_record(client, _KEY, data, status="published")


async def _stat(client, query: str) -> dict:
    resp = await client.get(f"{_STATS}?{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_count_at_the_cap_is_exact(plots):
    await _seed(plots, _CAP)
    assert await _stat(plots, "metric=count") == {"value": _CAP, "capped": False}


async def test_count_past_the_cap_is_the_cap(plots):
    """The listing's ``total`` and ``total_capped``, under the same name."""
    await _seed(plots, _CAP + 2)
    assert await _stat(plots, "metric=count") == {"value": _CAP, "capped": True}
    listed = (await plots.get(f"{PUBLIC}/{_KEY}")).json()
    assert (listed["total"], listed["total_capped"]) == (_CAP, True)


async def test_sum_at_the_cap_is_exact(plots):
    await _seed(plots, _CAP)
    assert await _stat(plots, "metric=sum:area") == {"value": 2 * _CAP, "capped": False}


async def test_sum_past_the_cap_is_not_available(plots):
    """A sum over the first ``max_count`` rows is not the sum: ``null``."""
    await _seed(plots, _CAP + 1)
    assert await _stat(plots, "metric=sum:area") == {"value": None, "capped": True}


async def test_bound_does_not_fill_with_hidden_rows(plots):
    """Drafts and the trash are narrowed away *inside* the ``LIMIT``: a bound
    that filled with them would call an exact answer capped."""
    await _seed(plots, _CAP)
    for n in range(2):
        await api_record(plots, _KEY, {"name": f"d-{n}", "area": 5}, status="draft")
    binned = await api_record(plots, _KEY, {"name": "binned", "area": 5}, status="published")
    gone = await plots.delete(
        f"/api/records/types/{_KEY}/records/{binned['uuid']}", headers=roles(ADMIN)
    )
    assert gone.status_code == 204
    assert await _stat(plots, "metric=count") == {"value": _CAP, "capped": False}
    assert await _stat(plots, "metric=sum:area") == {"value": 2 * _CAP, "capped": False}


async def test_filter_brings_it_back_under_the_cap(plots):
    """The bound counts the rows the filter keeps, not the type."""
    await _seed(plots, _CAP + 1, kind="a")
    await _seed(plots, 2, kind="b")
    assert await _stat(plots, "filter=kind:eq:b") == {"value": 2, "capped": False}
    got = await _stat(plots, "metric=sum:area&filter=kind:eq:b")
    assert got == {"value": 4, "capped": False}


async def test_filter_terms_bounded_like_the_listing(plots):
    """``parse_filters``' ``max_filter_terms`` applies here as on the listing."""
    limit = plots.app.state.sm_records.settings.max_filter_terms
    query = "&".join(["filter=kind:eq:a"] * (limit + 1))
    stats = await plots.get(f"{_STATS}?{query}")
    listed = await plots.get(f"{PUBLIC}/{_KEY}?{query}")
    assert stats.status_code == listed.status_code == 400
    assert stats.json() == listed.json()


async def test_bad_metric_says_so(plots):
    for metric in ("avg:area", "min:area", "max:area", "sum"):
        resp = await plots.get(f"{_STATS}?metric={metric}")
        assert resp.status_code == 400, (metric, resp.text)
        detail = resp.json()["detail"]
        assert "not a supported metric" in detail, (metric, detail)
        assert "filter or sort" not in detail, (metric, detail)
