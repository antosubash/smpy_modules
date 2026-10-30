"""Phase 4 review fixes, round 2: recovery pages advance past expired claims,
a fully deferred job is neither relaunched early nor struck, and a Retry-After
is bounded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.ingest.imports import launch, recover, retrying
from sm_images.ingest.imports.rate_limit import DomainLimiter, retry_after_seconds
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import JobStatus
from sqlalchemy import update

from tests.support.imports import HOST, URL, feature, serve_images

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT
OLD = timedelta(hours=1)


def url(name: str) -> str:
    return f"https://{HOST}/{name}"


async def _set(imp, model, *where, **values) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(update(model).where(*where).values(**values))
        await s.commit()


async def _reconcile(imp) -> tuple[int, int]:
    return await recover.recover_imports(imp.runtime, T, datetime.now(UTC) - timedelta(minutes=30))


@pytest.fixture
def no_sleep(monkeypatch):
    async def fake(_):
        return None

    monkeypatch.setattr(retrying, "_sleep", fake)


# --- 2. pages advance past expired claims ----------------------------------------


async def test_recovery_pages_advance_past_expired_claims(imp, monkeypatch):
    sent: list[list[int]] = []

    async def lagging(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))  # queued; no worker gets to them

    monkeypatch.setattr(launch, "launch_downloads", lagging)
    monkeypatch.setattr(recover, "ITEMS_PER_PASS", 2)
    job = await imp.job([feature({"url": url(f"{i}.jpg")}) for i in range(5)], URL)
    assert await imp.run(job) == "running"
    sent.clear()
    now = datetime.now(UTC)
    await _set(
        imp,
        ImportItem,
        ImportItem.job_id == job.id,
        claim_token="lost",
        claim_expires_at=now - timedelta(minutes=1),
        claim_generation=job.generation,
        updated_at=now - OLD,
    )
    await _set(imp, ImportJob, ImportJob.id == job.id, heartbeat_at=now)
    assert [(await _reconcile(imp))[1] for _ in range(4)] == [2, 2, 1, 0]
    flat = [i for batch in sent for i in batch]
    assert sorted(flat) == sorted(i.id for i in await imp.items(job))  # each once


# --- 3. deferred work is no breaker strike ----------------------------------------


async def test_a_long_retry_after_never_ends_stalled(imp, resolver, inner, no_sleep, monkeypatch):
    busy = httpx.Response(429, headers={"retry-after": "3600"})
    serve_images(resolver, inner, fail={"/busy.jpg": busy})
    job = await imp.job([feature({"url": url("busy.jpg")})], URL)
    assert await imp.run(job) == "running"
    runs: list[int] = []
    real = launch.launch_runner

    async def counted(runtime, tenant, job_id, generation):
        runs.append(generation)
        await real(runtime, tenant, job_id, generation)

    monkeypatch.setattr(launch, "launch_runner", counted)
    for _ in range(2 * recover.RELAUNCH_LIMIT):  # not due yet: left alone
        await _set(imp, ImportJob, ImportJob.id == job.id, heartbeat_at=datetime.now(UTC) - OLD)
        await _reconcile(imp)
    assert runs == []
    row = await imp.reload(job)
    assert (row.status, row.errors, row.relaunches) == (JobStatus.RUNNING, [], 0)
    for _ in range(retrying.MAX_ATTEMPTS - 2):  # due each time, and deferred again
        old = datetime.now(UTC) - OLD
        await _set(
            imp, ImportItem, ImportItem.job_id == job.id, next_attempt_at=old, updated_at=old
        )
        await _set(imp, ImportJob, ImportJob.id == job.id, heartbeat_at=old)
        await _reconcile(imp)
    row = await imp.reload(job)
    assert runs and row.status is JobStatus.RUNNING and row.errors == []
    (item,) = await imp.items(job)
    assert item.status.value == "pending" and item.next_attempt_at > datetime.now(UTC)


# --- 4. a Retry-After is bounded --------------------------------------------------


def _answer(value: str) -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": value})


async def test_retry_after_is_clamped_against_overflow():
    cap = retrying.MAX_RETRY_AFTER_SECONDS
    for raw in ("9" * 400, "99999999999999999999", "Fri, 31 Dec 9999 23:59:59 GMT"):
        got = retry_after_seconds(_answer(raw))
        assert got is not None and cap < got <= 2 * cap, raw
    assert retry_after_seconds(_answer("120")) == 120.0


async def _fetch(resolver, inner, value: str):
    resolver[HOST] = ["93.184.216.34"]
    inner(lambda request: _answer(value))

    class S:
        max_image_bytes = 1_000_000
        download_timeout = 5.0

    return await retrying.fetch_with_retries(url("x.jpg"), DomainLimiter(4, 8), S(), 0)


async def test_a_retry_after_beyond_a_day_fails_the_item(resolver, inner, no_sleep):
    with pytest.raises(retrying.Fail) as failed:
        await _fetch(resolver, inner, str(2 * 86400))
    assert failed.value.code == retrying.RETRY_AFTER_TOO_LONG
    with pytest.raises(retrying.Fail):
        await _fetch(resolver, inner, "9" * 400)


async def test_a_retry_after_within_a_day_defers_that_long(resolver, inner, no_sleep):
    with pytest.raises(retrying.Defer) as deferred:
        await _fetch(resolver, inner, str(23 * 3600))
    assert deferred.value.delay == 23 * 3600
