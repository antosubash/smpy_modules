"""Constraint patterns on every authenticated write path: matched in a worker
under a deadline, never on the event loop; verdicts are exact pairs."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from sm_records import _pattern_worker
from sm_records.schema._text_checks import checked, text_check
from sm_records.services import _patterns

from tests.app_harness import ADMIN, field, roles, seed_type

API = "/api/records/types"
EVIL = "^(a|aa)+$"
SLOW = "a" * 60 + "!"


@pytest.fixture(autouse=True)
def _short_budget(monkeypatch):
    monkeypatch.setattr(_patterns, "WRITE_BUDGET", 0.3)


async def _patterned(client, key: str = "note", pattern: str = EVIL) -> None:
    entry = field("name", indexed=False)
    entry["constraints"] = {"pattern": pattern}
    body = {"key": key, "label": key.title(), "fields": [entry]}
    resp = await client.post(API, json=body, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text


def _too_slow(resp) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"] == [{"field": "__root__", "message": "took too long to check"}]


async def _while_probing(client, write) -> tuple[object, float, float]:
    """Run ``write`` and, meanwhile, an unrelated read; return the write's
    answer, when the read finished and when the write did."""
    started = time.monotonic()
    task = asyncio.create_task(write)
    await asyncio.sleep(0.05)
    probe = await client.get(API, headers=roles(ADMIN))
    assert probe.status_code == 200
    probed = time.monotonic()
    resp = await task
    return resp, probed - started, time.monotonic() - started


async def test_a_create_cannot_pin_the_loop(client):
    await _patterned(client)
    write = client.post(f"{API}/note/records", json={"data": {"name": SLOW}}, headers=roles(ADMIN))
    resp, probed, finished = await _while_probing(client, write)
    _too_slow(resp)
    assert probed < finished < 4, "the read was answered while the pattern ran"


async def test_an_update_cannot_pin_the_loop(client):
    await _patterned(client)
    made = await client.post(
        f"{API}/note/records", json={"data": {"name": "aa"}}, headers=roles(ADMIN)
    )
    assert made.status_code == 201, made.text
    resp = await client.put(
        f"{API}/note/records/{made.json()['uuid']}",
        json={"expected_version": 1, "data": {"name": SLOW}},
        headers=roles(ADMIN),
    )
    _too_slow(resp)


async def test_an_import_checks_every_row_in_one_bounded_batch(client):
    await _patterned(client)
    rows = [{"data": {"name": SLOW + str(i)}} for i in range(30)]
    write = client.post(
        f"{API}/note/records/import?dry_run=false",
        content=json.dumps({"records": rows}),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    resp, probed, finished = await _while_probing(client, write)
    _too_slow(resp)
    assert probed < finished < 4


async def test_a_good_import_needs_one_worker_round_trip(client, monkeypatch):
    await _patterned(client)
    calls: list[int] = []
    real = _pattern_worker.PatternPool.check

    async def counted(self, checks, budget, **kwargs):
        calls.append(len(checks))
        return await real(self, checks, budget, **kwargs)

    monkeypatch.setattr(_pattern_worker.PatternPool, "check", counted)
    rows = [{"data": {"name": "a" * (i + 1)}} for i in range(20)]
    resp = await client.post(
        f"{API}/note/records/import?dry_run=false",
        content=json.dumps({"records": rows}),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 20
    assert calls == [20], "every row's value in one batch; the writes reuse its verdicts"


async def test_a_schema_change_checks_stored_values_in_the_worker(client):
    await _patterned(client, pattern="")
    made = await client.post(
        f"{API}/note/records", json={"data": {"name": SLOW}}, headers=roles(ADMIN)
    )
    assert made.status_code == 201, made.text
    rtype = (await client.get(f"{API}/note", headers=roles(ADMIN))).json()
    fields = [{**rtype["fields"][0], "constraints": {"pattern": EVIL}}]
    started = time.monotonic()
    resp = await client.post(
        f"{API}/note/schema/preview", json={"fields": fields}, headers=roles(ADMIN)
    )
    assert time.monotonic() - started < 4
    _too_slow(resp)


async def test_without_a_pattern_no_worker_is_started(client):
    made = await client.post(
        API, json={"key": "plain", "label": "P", "fields": [field("name")]}, headers=roles(ADMIN)
    )
    assert made.status_code == 201, made.text
    record = await client.post(
        f"{API}/plain/records", json={"data": {"name": SLOW}}, headers=roles(ADMIN)
    )
    assert record.status_code == 201
    assert not _pattern_worker.started()


async def test_a_verdict_covers_exactly_its_pair():
    """Security: verdicts are not an off switch. A pair with no verdict is
    matched as ever; a verdict decides only its own pattern and value."""
    check = text_check({"pattern": "^x+$"})
    with checked({("^x+$", "xx"): True, ("^other$", "nope"): True}):
        assert check("xx") == "xx"
        assert check("x") == "x", "matched normally: no verdict for it"
        with pytest.raises(ValueError, match="must match"):
            check("nope")
    with checked({("^x+$", "y"): False}), pytest.raises(ValueError):
        check("y")
    with pytest.raises(ValueError):
        check("zz")


SLOW_DEFAULT = "^(a+)+$|!$"


async def test_a_backtracking_default_is_checked_in_the_worker_on_save(client):
    entry = field("name", indexed=False)
    entry["constraints"] = {"pattern": SLOW_DEFAULT}
    entry["default"] = "a" * 40 + "!"
    body = {"key": "slowdefault", "label": "S", "fields": [entry]}
    started = time.monotonic()
    resp = await client.post(API, json=body, headers=roles(ADMIN))
    assert time.monotonic() - started < 4
    _too_slow(resp)
    entry["constraints"] = {"pattern": "^x+$"}
    entry["default"] = "y"
    refused = await client.post(API, json=body, headers=roles(ADMIN))
    assert refused.status_code == 422, refused.text
    assert refused.json()["errors"] == [
        {"field": "name", "message": "default is invalid: must match ^x+$"}
    ]
    entry["default"] = "xx"
    assert (await client.post(API, json=body, headers=roles(ADMIN))).status_code == 201


async def test_a_stored_default_is_never_matched_again_on_load(client):
    """A type whose stored default would backtrack: loading the schema (every
    record read and write does) does not match it."""
    entry = field("name", indexed=False)
    entry["constraints"] = {"pattern": SLOW_DEFAULT}
    entry["default"] = "a" * 40 + "!"
    await seed_type(client.db_state, "stored", [entry])
    started = time.monotonic()
    assert (await client.get(f"{API}/stored", headers=roles(ADMIN))).status_code == 200
    listed = await client.get(f"{API}/stored/records", headers=roles(ADMIN))
    assert listed.status_code == 200
    made = await client.post(
        f"{API}/stored/records", json={"data": {"name": "!"}}, headers=roles(ADMIN)
    )
    assert made.status_code == 201, made.text
    assert time.monotonic() - started < 4


async def test_a_batch_whose_answer_exceeds_64_kib_is_framed():
    pairs = [("^a", f"a{i}") for i in range(100_000)]
    found = await _pattern_worker.pool().check(pairs, 30)
    assert found is not None and len(found) == len(pairs) and all(found)
    await _pattern_worker.close()


async def test_a_garbled_worker_answer_is_a_clean_refusal(client, monkeypatch):
    await _patterned(client)
    await _pattern_worker.close()
    garbled = "import sys\nfor _ in sys.stdin: print('{]', flush=True)"
    monkeypatch.setattr(_pattern_worker, "_WORKER", garbled)
    resp = await client.post(
        f"{API}/note/records", json={"data": {"name": "aa"}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"] == [{"field": "__root__", "message": "could not be checked"}]
