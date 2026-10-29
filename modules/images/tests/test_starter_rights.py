"""Whole-collection restarts and prompt runs re-check the starter's right (M7).

Like imports and regroups (``imports.access``), a background run over a whole
collection records who started it and on what basis, and the worker re-checks
that right before each chunk. Both need owner or ``images.manage`` (shares
never), so a starter who no longer owns the collection, or a manager who is no
longer active in the tenant, stops the run and the tenant's AI quota is not
spent on their behalf.
"""

from __future__ import annotations

import dataclasses
import uuid

from sm_images.ai import run as prompt_run
from sm_images.imports.access import MANAGE, OWNER
from sm_images.models import Collection, PipelineRestart
from sm_images.pipeline import restart
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.access_support import OWNER as OLGA
from tests.access_support import headers
from tests.ai_support import add_prompt
from tests.pipeline_api_support import url
from tests.pipeline_support import Scripted, use_steps
from tests.stub_auth import user_uuid

T = DEFAULT_TENANT


def _record(monkeypatch, module) -> list[uuid.UUID]:
    sent: list[uuid.UUID] = []

    async def dispatch(runtime, tenant, image_id):
        sent.append(image_id)

    monkeypatch.setattr(module, "submit_dispatch", dispatch)
    return sent


async def _give_away(pipe, coll, owner: str = "someone-else") -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Collection).where(Collection.id == coll.id).values(owner_id=owner))
        await s.commit()


async def _restarts(pipe) -> list[PipelineRestart]:
    async with pipe.db_state.session_factory() as s:
        return list((await s.execute(select(PipelineRestart))).scalars())


async def test_a_restart_stops_once_its_starter_lost_the_right(pipe, monkeypatch):
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    for _ in range(3):
        await pipe.image(coll)
    sent = _record(monkeypatch, restart)
    rid = await restart.start_restart(
        pipe.runtime, T, coll.id, "force", run_as=coll.owner_id, access_basis=OWNER
    )
    await _give_away(pipe, coll)
    assert await restart.resume_restart(pipe.runtime, T, rid) == 0
    assert sent == []
    (row,) = await _restarts(pipe)
    assert row.finished_at is not None  # stopped for good, not resumed by reconcile


async def test_a_restart_by_the_owner_runs(pipe, monkeypatch):
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    for _ in range(3):
        await pipe.image(coll)
    sent = _record(monkeypatch, restart)
    await restart.restart_collection_async(
        pipe.runtime, T, coll.id, "force", run_as=coll.owner_id, access_basis=OWNER
    )
    assert len(sent) == 3


async def test_a_managers_restart_stops_once_they_are_gone(pipe, monkeypatch):
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    await pipe.image(coll)
    sent = _record(monkeypatch, restart)
    # No such user: ``manager_active`` is false, as for a deleted or deactivated one.
    gone = str(uuid.uuid4())
    await restart.restart_collection_async(
        pipe.runtime, T, coll.id, "force", run_as=gone, access_basis=MANAGE
    )
    assert sent == []


async def test_a_queued_prompt_run_stops_once_its_starter_lost_the_right(pipe, monkeypatch):
    coll = await pipe.collection({})
    await pipe.image(coll)
    prompt = await add_prompt(pipe, coll)
    sent = _record(monkeypatch, prompt_run)
    await _give_away(pipe, coll)
    got = await prompt_run.run_prompt(
        pipe.runtime, T, prompt.id, "all", run_as="olga", access_basis=OWNER
    )
    assert (got, sent) == (0, [])
    await _give_away(pipe, coll, "olga")
    got = await prompt_run.run_prompt(
        pipe.runtime, T, prompt.id, "all", run_as="olga", access_basis=OWNER
    )
    assert got == 1 and len(sent) == 1


async def test_the_restart_route_records_its_starter(world):
    r = await world.c.post(url(world, "/restart"), json={"scope": "all"}, headers=headers(OLGA))
    assert r.status_code == 202, r.text
    async with world.c.db_state.session_factory() as s:
        (row,) = (await s.execute(select(PipelineRestart))).scalars()
    assert (row.run_as, row.access_basis) == (user_uuid(OLGA), OWNER)


async def test_a_queued_prompt_run_carries_its_starter(pipe, monkeypatch):
    from sm_images import tasks

    sent = {}

    class Sig:
        def __init__(self, *args, **kwargs):
            sent.update(args=args, kwargs=kwargs)

        def apply_async(self, **kw):
            sent["queued"] = kw

    monkeypatch.setattr(tasks.run_prompt_task, "s", Sig)
    broker = dataclasses.replace(pipe.runtime, eager=False)
    pid = uuid.uuid4()
    await prompt_run.launch(broker, T, pid, "all", None, None, run_as="olga", access_basis=OWNER)
    assert sent["args"] == (str(pid), "all")
    assert sent["kwargs"] == {"run_as": "olga", "access_basis": OWNER}
