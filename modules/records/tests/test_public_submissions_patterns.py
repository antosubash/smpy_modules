"""Constraint patterns on website input (#101): exactly ``re``'s meaning, never
matched on the event loop, and one deadline for the whole submission."""

from __future__ import annotations

import asyncio
import time

import pytest
from sm_records import _pattern_worker
from sm_records.public_submissions import patterns

from tests.app_harness import ADMIN, field, roles
from tests.public_submissions_support import API, create, form_config
from tests.submissions_http import SUBMISSIONS, load, records_of, send


async def _patterned(site, key: str, pattern: str) -> None:
    name = field("name", indexed=False)
    name["constraints"] = {"pattern": pattern}
    config = form_config(enabled=True, public_fields=["name"])
    resp = await create(site, key, fields=[name], config=config)
    assert resp.status_code == 201, resp.text


async def _verdicts(site, key: str, values: list[str]) -> tuple[list[int], list[int]]:
    """``(public statuses, admin statuses)`` for each value."""
    public, admin = [], []
    for value in values:
        public.append((await send(site, key, data={"name": value})).status_code)
        made = await site.post(
            f"{API}/{key}/records", json={"data": {"name": value}}, headers=roles(ADMIN)
        )
        admin.append(made.status_code)
    return public, admin


@pytest.mark.parametrize(
    ("pattern", "values", "public", "admin"),
    [
        # ``re``'s \w is alphanumerics and underscore: "é" matches, a bare
        # combining accent does not (``regex`` would have taken it).
        (r"^\w+$", ["é", "é", "a_1"], [202, 422, 202], [201, 422, 201]),
        # For ``re`` the braces are literal; ``regex`` would read fuzzy matching.
        (r"^a{e<=1}$", ["a{e<=1}", "b", "a"], [202, 422, 422], [201, 422, 422]),
    ],
    ids=["word", "braces"],
)
async def test_a_pattern_means_what_re_means_on_both_paths(site, pattern, values, public, admin):
    await _patterned(site, "patterned", pattern)
    assert await _verdicts(site, "patterned", values) == (public, admin)
    assert len(await records_of(site, "patterned")) == public.count(202) + admin.count(201)


async def test_eighty_backtracking_fields_are_refused_fast_and_the_loop_stays_free(site):
    keys = [f"f{i}" for i in range(80)]
    fields = []
    for key in keys:
        entry = field(key, indexed=False)
        entry["constraints"] = {"pattern": "^(a|aa)+$"}
        fields.append(entry)
    config = form_config(enabled=True, public_fields=keys)
    assert (await create(site, "evil", fields=fields, config=config)).status_code == 201
    token = (await load(site, "evil"))["token"]
    evil = dict.fromkeys(keys, "a" * 60 + "!")

    started = time.monotonic()
    submit = asyncio.create_task(send(site, "evil", data=evil, token=token))
    await asyncio.sleep(0.05)
    probe = await site.get(f"{SUBMISSIONS}/evil")
    probed = time.monotonic()
    resp = await submit
    finished = time.monotonic()

    assert probe.status_code == 200
    assert probed < finished, "another request was answered while the patterns ran"
    assert finished - started < patterns.BUDGET_SECONDS + 3
    assert (resp.status_code, resp.json()["code"]) == (422, "invalid")
    assert resp.json()["errors"] == [{"field": "__root__", "message": "took too long to check"}]
    assert await records_of(site, "evil") == []
    ok = dict.fromkeys(keys, "aa")
    assert (await send(site, "evil", data=ok)).status_code == 202, "a fresh worker took over"


async def test_without_patterns_no_worker_is_started(site):
    await _patterned(site, "plain", "")
    assert (await send(site, "plain", data={"name": "x"})).status_code == 202
    assert not _pattern_worker.started()
