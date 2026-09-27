"""Schema previews that are too big to be a request — design §8.9, F10.

A dry run validates every record of a type, trash included, against a
*proposed* model, at roughly a thousand records a second. On a type holding a
few thousand that is a request; on one holding forty-five thousand it is forty
seconds of HTTP, with whatever proxy timeout that implies, for an answer the
operator is going to read on a screen that could perfectly well show a
progress bar. So ``POST /types/{key}/schema/preview`` stays synchronous up to
``RecordsSettings.preview_sync_limit`` records and answers ``202`` with a job
id above it, running the scan through the module's own deferred-job mechanism
(:mod:`sm_records.deferred`) on its own session.

**The registry is in-process and deliberately so.** §8.9 already says no
report is ever persisted: a report is a claim about records as they were when
it was taken, and storing one invites a caller to apply it later against a
database it no longer describes. These entries are the same claim with a
lifetime — bounded by count, pruned by age, and gone on restart, which is the
correct behaviour rather than a limitation. A host running several workers
will land a poll on a worker that never ran the job and answer 404; the client
falls back to the synchronous path, which is what it would have done anyway.

The one place a report is *reused* is ``PUT /types/{key}``
(:func:`sm_records.services.schema_change.apply`), under the guard
:func:`reusable` states.

**A job belongs to one tenant's type** (tenancy design §H). The registry is
process-global, so each job records ``tenant_id`` and ``type_id``. The poll
endpoint matches the job on ``type_id`` and never on the key, because two
tenants can hold the same key under different ids. The runner binds the job's
``tenant_id`` (:mod:`sm_records.services.preview_runner`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sm_records.schema.changes import DryRunReport, SchemaDiff
from sm_records.services._common import utcnow

__all__ = [
    "MAX_JOBS",
    "PreviewJob",
    "fail",
    "fields_hash",
    "finish",
    "get",
    "get_for_type",
    "progress",
    "reusable",
    "start",
]

MAX_JOBS = 50
"""How many jobs the registry keeps. Small on purpose: each holds a report
with at most ``DRY_RUN_SAMPLE`` failing records, and a schema editor is one
operator at a time on one type at a time."""

_RUNNING = "running"
_DONE = "done"
_FAILED = "failed"


@dataclass
class PreviewJob:
    """One running or finished dry run."""

    id: str
    tenant_id: str
    """The tenant the type belongs to, and the one the deferred scan runs in."""
    type_key: str
    type_id: int
    type_version: int
    """``RecordType.version`` when the scan started — what :func:`reusable`
    compares against, so a report taken before a schema edit is never reused
    after one."""
    signature: str
    status: str = _RUNNING
    checked: int = 0
    total: int = 0
    report: DryRunReport | None = None
    diff: SchemaDiff | None = None
    error: str | None = None
    finished_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.status == _DONE


_jobs: dict[str, PreviewJob] = {}


def fields_hash(
    fields_raw: Any,
    display_field: Any = None,
    slug_field: Any = None,
    *,
    rescan: bool = False,
) -> str:
    """A digest of *what was previewed*, not of the type.

    Everything that changes what the dry run would conclude goes in: the
    proposed field list, both pointers, and ``rescan``. ``default=str``
    because a raw field definition is plain JSON in practice but is not
    guaranteed to be — a stray ``Decimal`` from a caller must produce a stable
    digest rather than a ``TypeError`` in the middle of a preview.

    ``rescan`` is in the digest so an *apply* can never reuse a "Check
    records" report (``_preview.reused_report``). That report answers a
    different question — what the schema refuses now, rather than what the
    change would break — and a save of the same field list would inherit its
    ``failing`` count and be refused for records the change does not touch.
    """
    payload = json.dumps(
        {"f": fields_raw, "d": display_field, "s": slug_field, "r": rescan},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _prune(ttl_seconds: int) -> None:
    """Drop what is too old, then what is merely too much.

    Age first and by *finish* time: a running job has no age worth measuring
    and must survive its own registration. The count bound then drops the
    oldest finished jobs, never a running one — evicting a job whose scan is
    still going would make its poll 404 while the work continued invisibly.
    """
    now = utcnow()
    for job_id, job in list(_jobs.items()):
        if job.finished_at is not None and (now - job.finished_at).total_seconds() > ttl_seconds:
            del _jobs[job_id]
    finished = sorted(
        (job for job in _jobs.values() if job.finished_at is not None),
        key=lambda job: job.finished_at or now,
    )
    for job in finished[: max(len(_jobs) - MAX_JOBS, 0)]:
        _jobs.pop(job.id, None)


def start(
    *,
    tenant_id: str,
    type_key: str,
    type_id: int,
    type_version: int,
    signature: str,
    total: int,
    ttl_seconds: int,
) -> PreviewJob:
    job = PreviewJob(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        type_key=type_key,
        type_id=type_id,
        type_version=type_version,
        signature=signature,
        total=total,
    )
    _jobs[job.id] = job
    # After the insert, not before it, so the bound holds *including* the job
    # just started. The new one is running and :func:`_prune` only evicts
    # finished jobs, so it cannot evict itself.
    _prune(ttl_seconds)
    return job


def get(job_id: str) -> PreviewJob | None:
    return _jobs.get(job_id)


def get_for_type(job_id: str, type_id: int) -> PreviewJob | None:
    """The job, only when it was started for this ``type_id``.

    Type ids are global and the caller loaded the type under its own tenant,
    so this also keeps a job id started in one tenant from being read
    through another tenant's type with the same key.
    """
    job = _jobs.get(job_id)
    return job if job is not None and job.type_id == type_id else None


def progress(job_id: str, checked: int) -> None:
    """How far the scan has got, written per batch by the dry run itself."""
    job = _jobs.get(job_id)
    if job is not None:
        job.checked = checked


def finish(job_id: str, diff: SchemaDiff, report: DryRunReport) -> None:
    job = _jobs.get(job_id)
    if job is None:  # pragma: no cover - only if the registry was pruned mid-run
        return
    job.diff, job.report, job.checked = diff, report, report.checked
    job.status, job.finished_at = _DONE, utcnow()


def fail(job_id: str, message: str) -> None:
    job = _jobs.get(job_id)
    if job is None:  # pragma: no cover - see finish
        return
    job.error, job.status, job.finished_at = message, _FAILED, utcnow()


def reusable(
    *, type_id: int, type_version: int, signature: str, ttl_seconds: int
) -> PreviewJob | None:
    """A finished job ``apply`` may take its report from instead of re-scanning.

    Three conditions, and the third is the one doing the work. Same type, same
    proposed fields — and **the type's ``version`` has not moved**, which is
    the same value ``apply`` has already required the caller to send as
    ``expected_version`` and has already checked under the row lock. So the
    schema the report was taken against is provably the schema being changed:
    no field was added, removed, retyped or re-pointed in between, and the
    diff the report describes is the diff about to be applied.

    What the version does *not* cover is the records, which are written
    without moving it. That is what ``ttl_seconds`` bounds, and why the
    default is ten minutes rather than a day: the window is short, the writes
    in it were themselves validated against the *current* schema, and the only
    thing at stake is whether a record written inside it would have failed the
    *new* one — which ``force`` exists for and which the next ordinary write
    of that record resolves either way (§8.3 — marked, not mutated). A caller
    that wants the guarantee unconditionally sets ``preview_job_ttl_seconds``
    to 0, which turns every ``PUT`` back into its own inline pass.

    **Same type means the same ``type_id``, never the same key.** A key is not
    an identity (``schema.compile.get_model``): a type can be deleted and
    recreated under the same key inside the TTL, restarting at ``version = 1``
    — and a job taken against the old rows would then satisfy a key-and-version
    match exactly, handing ``apply`` a ``checked``/``failing`` count computed
    over records that no longer exist and skipping the scan of the ones that
    do. The id is what the registry already stores, and it never comes back.
    """
    if ttl_seconds <= 0:
        return None
    now = utcnow()
    for job in _jobs.values():
        if (
            job.done
            and job.type_id == type_id
            and job.type_version == type_version
            and job.signature == signature
            and job.report is not None
            and job.finished_at is not None
            and (now - job.finished_at).total_seconds() <= ttl_seconds
        ):
            return job
    return None
