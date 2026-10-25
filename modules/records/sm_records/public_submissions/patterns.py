"""Constraint patterns on a website visitor's input (#101).

The same worker check every write path uses (:mod:`sm_records.services.
_patterns`, :mod:`sm_records._pattern_worker`), with the public path's
tighter terms: one :data:`BUDGET_SECONDS` for the whole submission, at most
:data:`WAIT_SECONDS` to get a worker (else ``429``), and a value that misses
its pattern refused here with the field named — before ``create_record``
validates anything. The verdicts are returned so the write can validate
inside ``checked(...)`` and send nothing to a worker twice.
"""

from __future__ import annotations

from typing import Any, Final

from sm_records import _pattern_worker
from sm_records.models import RecordType
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.schema._text_checks import Verdicts
from sm_records.services._patterns import NOT_CHECKED, TOO_SLOW, pairs_of
from sm_records.services._payload import field_defs

__all__ = ["BUDGET_SECONDS", "WAIT_SECONDS", "check_patterns"]

BUDGET_SECONDS: Final = 0.5
"""Wall-clock budget for every pattern match of one submission together."""

WAIT_SECONDS: Final = 2.0


async def check_patterns(rtype: RecordType, data: dict[str, Any]) -> Verdicts:
    """Refuse ``data`` if a value misses its field's pattern, or if checking
    them all takes longer than the budget. Empty without patterns."""
    defs = [entry for entry in field_defs(rtype) if not entry.system]
    pending = sorted(pairs_of(defs, [data]))
    if not pending:
        return {}
    try:
        found = await _pattern_worker.pool().check(pending, BUDGET_SECONDS, wait=WAIT_SECONDS)
    except _pattern_worker.PoolBusy:
        raise SubmissionRefused(
            "rate_limited", "too many submissions; try again", headers={"Retry-After": "1"}
        ) from None
    except _pattern_worker.WorkerFailed as exc:
        raise SubmissionRefused(
            "invalid",
            f"this submission {NOT_CHECKED}",
            errors=[{"field": "__root__", "message": NOT_CHECKED}],
        ) from exc
    if found is None:
        raise SubmissionRefused(
            "invalid",
            f"this submission {TOO_SLOW}",
            errors=[{"field": "__root__", "message": TOO_SLOW}],
        )
    verdicts = dict(zip(pending, found, strict=True))
    failed = [
        (entry.key, entry.constraints["pattern"])
        for entry in defs
        if (entry.constraints or {}).get("pattern")
        and isinstance(data.get(entry.key), str)
        and verdicts.get((entry.constraints["pattern"], data[entry.key])) is False
    ]
    if failed:
        raise SubmissionRefused(
            "invalid",
            f"{failed[0][0]!r} does not match its pattern",
            errors=[{"field": key, "message": f"must match {pattern}"} for key, pattern in failed],
        )
    return verdicts
