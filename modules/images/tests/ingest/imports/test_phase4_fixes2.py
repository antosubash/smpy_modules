"""Phase 4 review fixes (P2): a trashed collection fences its imports, a
Retry-After is kept, a redirect hop takes its own host's slot, and recovery
works in bounded passes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.ingest.imports import launch, recover, retrying, settle
from sm_images.ingest.imports.rate_limit import domain_of
from sm_images.models import Collection, ImportItem, ImportJob
from sm_images.models.enums import JobStatus
from sqlalchemy import update

from tests.support.fetch import PUBLIC_IP, body
from tests.support.imports import HOST, URL, b64, feature, serve_images
from tests.support.pipeline import jpeg

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT
OLD = timedelta(hours=1)


def url(name: str) -> str:
    return f"https://{HOST}/{name}"


@pytest.fixture
def broker(monkeypatch):
    sent: list[list[int]] = []

    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))

    monkeypatch.setattr(launch, "launch_downloads", fake)
    return sent


async def _age(imp, model, *where, **values) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(update(model).where(*where).values(**values))
        await s.commit()


async def _reconcile(imp) -> tuple[int, int]:
    return await recover.recover_imports(imp.runtime, T, datetime.now(UTC) - timedelta(minutes=30))


# --- 4. a trashed collection's settlements lose ------------------------------


async def test_a_settlement_into_a_trashed_collection_rolls_back(imp, monkeypatch):
    real = settle.ingest_item

    async def trash_first(ingest, *a, **k):
        out = await real(ingest, *a, **k)
        # Trashed meanwhile (in this transaction: SQLite here shares one connection).
        trash = update(Collection).where(Collection.id == imp.coll.id).values(is_deleted=True)
        await ingest.db.execute(trash)
        return out

    monkeypatch.setattr(settle, "ingest_item", trash_first)
    job = await imp.job([feature({"img": b64()})])
    await imp.run(job)
    assert await imp.statuses(job) == ["pending"]
    assert await imp.images() == []


# --- 5. a Retry-After is kept ---------------------------------------------------


async def test_a_one_hour_retry_after_is_honoured_by_recovery_and_claims(
    imp, resolver, inner, monkeypatch
):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(retrying, "_sleep", no_sleep)
    seen = serve_images(
        resolver, inner, fail={"/busy.jpg": httpx.Response(429, headers={"retry-after": "3600"})}
    )
    job = await imp.job([feature({"url": url("busy.jpg")})], URL)
    assert await imp.run(job) == "running"
    (item,) = await imp.items(job)
    due = item.next_attempt_at
    assert due is not None
    assert timedelta(minutes=59) < due - datetime.now(UTC) <= timedelta(hours=1, minutes=1)
    await _age(imp, ImportItem, ImportItem.id == item.id, updated_at=datetime.now(UTC) - OLD)
    fetched = len(seen)
    assert (await _reconcile(imp))[1] == 0  # not due: not re-sent
    from sm_images.ingest.imports import download

    assert await download.download_items_async(imp.runtime, T, job.id, 0, [item.id]) == 0
    assert len(seen) == fetched  # a claim skips it too
    past = datetime.now(UTC) - timedelta(seconds=1)
    old = datetime.now(UTC) - OLD
    await _age(imp, ImportItem, ImportItem.id == item.id, next_attempt_at=past, updated_at=old)
    assert (await _reconcile(imp))[1] == 1
    assert len(seen) > fetched


# --- 6. every redirect hop holds its own host's slot ---------------------------


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    @asynccontextmanager
    async def slot(self, target: str):
        self.events.append(("enter", domain_of(target)))
        try:
            yield
        finally:
            self.events.append(("exit", domain_of(target)))


async def test_a_redirect_takes_the_destination_hosts_slot(resolver, inner):
    resolver[HOST] = [PUBLIC_IP]
    resolver["cdn.example"] = [PUBLIC_IP]

    def handler(request):
        if request.headers["host"] == HOST:
            return httpx.Response(302, headers={"location": "https://cdn.example/x.jpg"})
        return body(jpeg((8, 6), "red"))

    inner(handler)
    limiter = Recorder()

    class S:
        max_image_bytes = 10_000_000
        download_timeout = 10.0

    data, attempts = await retrying.fetch_with_retries(url("r.jpg"), limiter, S(), 0)
    assert data and attempts == 1
    assert limiter.events == [
        ("enter", HOST),
        ("exit", HOST),  # the previous hop's slot goes first: no hold-and-wait
        ("enter", "cdn.example"),
        ("exit", "cdn.example"),
    ]


# --- 7. recovery works in bounded passes ----------------------------------------


async def test_recovery_re_sends_a_bounded_page_and_continues_next_pass(imp, broker, monkeypatch):
    monkeypatch.setattr(recover, "ITEMS_PER_PASS", 2)
    job = await imp.job([feature({"url": url(f"{i}.jpg")}) for i in range(5)], URL)
    assert await imp.run(job) == "running"
    broker.clear()
    await _age(imp, ImportItem, ImportItem.job_id == job.id, updated_at=datetime.now(UTC) - OLD)
    await _age(imp, ImportJob, ImportJob.id == job.id, heartbeat_at=datetime.now(UTC))
    passes = [(await _reconcile(imp))[1] for _ in range(4)]
    assert passes == [2, 2, 1, 0]
    sent = [i for batch in broker for i in batch]
    assert sorted(sent) == sorted(i.id for i in await imp.items(job))  # each once


async def test_recovery_relaunches_a_bounded_number_of_jobs(imp, monkeypatch):
    monkeypatch.setattr(recover, "JOBS_PER_PASS", 1)
    launched: list = []

    async def backlog(runtime, tenant, job_id, generation):
        launched.append(job_id)

    monkeypatch.setattr(launch, "launch_runner", backlog)
    jobs = [await imp.job([feature({"img": b64()})]) for _ in range(2)]
    for j in jobs:
        await _age(imp, ImportJob, ImportJob.id == j.id, heartbeat_at=datetime.now(UTC) - OLD)
    assert (await _reconcile(imp))[0] == 1
    assert (await _reconcile(imp))[0] == 1
    assert sorted(launched) == sorted(j.id for j in jobs)
    assert {(await imp.reload(j)).status for j in jobs} == {JobStatus.PENDING}
