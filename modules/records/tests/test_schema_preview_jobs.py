"""``POST /schema/preview`` above ``preview_sync_limit`` — F10.

The synchronous path is covered by ``test_api_schema.py``; what is new is
that the same request answers ``202`` with a job id on a big type, that the
job reports progress and finishes with the *same* report, and that a ``PUT``
close behind it reuses that report instead of scanning again.
"""

from __future__ import annotations

import pytest
from sm_records.services import preview_jobs
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"


@pytest.fixture(autouse=True)
def _empty_registry():
    """The registry is process-global by design (it is in-process state, not a
    table), so a job one test leaves behind is visible to the next — which is
    exactly how ``reusable`` would be proved by accident."""
    preview_jobs._jobs.clear()
    yield
    preview_jobs._jobs.clear()


def _field(key: str, type_: str, *, required: bool = False) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": required,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": {},
    }


async def _seed(client, count: int) -> dict:
    body = {
        "key": "note",
        "label": "Note",
        "fields": [_field("title", "text"), _field("body", "text")],
        "display_field": "title",
    }
    made = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert made.status_code == 201, made.text
    for n in range(count):
        created = await client.post(
            f"{_API}/note/records", json={"data": {"title": f"n{n}"}}, headers=roles(ADMIN)
        )
        assert created.status_code == 201, created.text
    return made.json()


def _restrictive(rtype: dict) -> list[dict]:
    fields = [dict(raw) for raw in rtype["fields"]]
    for raw in fields:
        if raw["key"] == "body":
            raw["required"] = True
    return fields


async def test_a_small_type_previews_synchronously(client):
    rtype = await _seed(client, 3)
    resp = await client.post(
        f"{_API}/note/schema/preview", json={"fields": _restrictive(rtype)}, headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    assert resp.json()["report"]["checked"] == 3


async def test_a_big_type_previews_as_a_job(client):
    rtype = await _seed(client, 3)
    client.app.state.sm_records.settings = RecordsSettings(preview_sync_limit=1)
    resp = await client.post(
        f"{_API}/note/schema/preview", json={"fields": _restrictive(rtype)}, headers=roles(ADMIN)
    )
    assert resp.status_code == 202
    job_id = resp.json()["job"]
    assert resp.json()["status"] == "running"

    # ``DeferredJobsMiddleware`` drains after the response, so by the time the
    # 202 is in hand the scan has already run in this single-process harness.
    state = await client.get(f"{_API}/note/schema/preview/{job_id}", headers=roles(ADMIN))
    assert state.status_code == 200
    body = state.json()
    assert body["status"] == "done"
    assert (body["checked"], body["total"]) == (3, 3)
    assert body["preview"]["report"]["failing"] == 3


async def test_an_unknown_job_is_a_404(client):
    await _seed(client, 1)
    missing = await client.get(f"{_API}/note/schema/preview/nope", headers=roles(ADMIN))
    assert missing.status_code == 404


async def test_a_job_is_not_readable_under_another_type(client):
    rtype = await _seed(client, 3)
    client.app.state.sm_records.settings = RecordsSettings(preview_sync_limit=1)
    job_id = (
        await client.post(
            f"{_API}/note/schema/preview",
            json={"fields": _restrictive(rtype)},
            headers=roles(ADMIN),
        )
    ).json()["job"]
    other = {"key": "other", "label": "Other", "fields": [_field("title", "text")]}
    assert (
        await client.post("/api/records/types", json=other, headers=roles(ADMIN))
    ).status_code == 201
    wrong = await client.get(f"{_API}/other/schema/preview/{job_id}", headers=roles(ADMIN))
    assert wrong.status_code == 404


async def test_apply_reuses_a_matching_job_report(client, monkeypatch):
    rtype = await _seed(client, 3)
    client.app.state.sm_records.settings = RecordsSettings(preview_sync_limit=1)
    fields = _restrictive(rtype)
    assert (
        await client.post(
            f"{_API}/note/schema/preview", json={"fields": fields}, headers=roles(ADMIN)
        )
    ).status_code == 202

    # Any second scan would go through ``change_report``; making it explode is
    # the only way to prove the apply did not run one.
    from sm_records.services import schema_change as module

    async def _boom(*args, **kwargs):  # pragma: no cover - fails the test if reached
        raise AssertionError("apply re-ran the dry run instead of reusing the preview")

    monkeypatch.setattr(module, "change_report", _boom)
    resp = await client.put(
        f"{_API}/note",
        json={"expected_version": rtype["version"], "fields": fields, "force": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text


async def test_a_stale_version_is_not_reused(client):
    """The guard is the type's ``version``: a job taken before another edit
    describes a schema that is no longer the one being changed."""
    rtype = await _seed(client, 3)
    job = preview_jobs.start(
        type_key="note",
        type_id=1,
        type_version=rtype["version"] - 1,
        signature=preview_jobs.fields_hash(_restrictive(rtype), "title", None),
        total=3,
        ttl_seconds=600,
    )
    assert (
        preview_jobs.reusable(
            type_key="note",
            type_version=rtype["version"],
            signature=job.signature,
            ttl_seconds=600,
        )
        is None
    )


async def test_the_registry_is_bounded(client):
    for n in range(preview_jobs.MAX_JOBS + 10):
        job = preview_jobs.start(
            type_key=f"t{n}",
            type_id=n,
            type_version=1,
            signature=str(n),
            total=0,
            ttl_seconds=600,
        )
        preview_jobs.fail(job.id, "done with it")
    preview_jobs.start(
        type_key="last", type_id=0, type_version=1, signature="z", total=0, ttl_seconds=600
    )
    assert len(preview_jobs._jobs) <= preview_jobs.MAX_JOBS
