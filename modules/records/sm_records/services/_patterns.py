"""Checking constraint patterns before a write validates, off the event loop.

Every write path that validates values somebody sent against a type's
``constraints.pattern`` calls :func:`precheck` first — ``_prepare.prepare``
(every create and update: the API, translations, a revision restore, bulk
actions, the CLI, the seeder, a submission's system writes), an import for
all its rows at once, and a schema change's dry run per batch — and then
validates inside :func:`~sm_records.schema._text_checks.checked`. The worker
(:mod:`sm_records._pattern_worker`) runs every pending ``(pattern, value)``
pair of the call in one batch under one budget; past it the write is refused
with a 422 and nothing further is validated. Pairs already decided in scope
(a website submission checked its own, an import checked all its rows) are
not sent again, and a payload with no patterned value never reaches a worker.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from sm_records import _pattern_worker
from sm_records.schema._text_checks import Verdicts, verdicts
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import FieldType
from sm_records.services.errors import ValidationFailed

__all__ = ["WRITE_BUDGET", "batch_budget", "pairs_of", "precheck"]

WRITE_BUDGET: Final = 2.0
"""Seconds for every pattern of one authenticated write together."""

_PER_VALUE: Final = 0.002
_CAP: Final = 10.0

_TEXTLIKE: Final = frozenset({FieldType.TEXT, FieldType.LONGTEXT, FieldType.EMAIL, FieldType.URL})

TOO_SLOW: Final = "took too long to check"


def batch_budget(values: int) -> float:
    """A batch of many records' values (an import, a dry-run batch): the
    write budget plus a little per value, capped."""
    return min(WRITE_BUDGET + _PER_VALUE * values, _CAP)


def pairs_of(
    defs: Iterable[FieldDefinition], payloads: Iterable[Mapping[str, Any]]
) -> set[tuple[str, str]]:
    """Every ``(pattern, value)`` the validator would match for ``payloads`` —
    a missing key's default included, since the validator checks that too."""
    patterned = [
        (entry.key, entry.constraints["pattern"], entry.default)
        for entry in defs
        if entry.type in _TEXTLIKE and (entry.constraints or {}).get("pattern")
    ]
    if not patterned:
        return set()
    out: set[tuple[str, str]] = set()
    for payload in payloads:
        for key, pattern, default in patterned:
            value = payload.get(key, default)
            if isinstance(value, str):
                out.add((pattern, value))
    return out


async def precheck(
    defs: Iterable[FieldDefinition],
    payloads: Iterable[Mapping[str, Any]],
    *,
    budget: float | None = None,
) -> Verdicts:
    """The verdicts for every pair the scope has not decided yet."""
    known = verdicts()
    pending = sorted(pair for pair in pairs_of(defs, payloads) if pair not in known)
    if not pending:
        return {}
    found = await _pattern_worker.pool().check(pending, WRITE_BUDGET if budget is None else budget)
    if found is None:
        raise ValidationFailed(
            f"checking the field patterns {TOO_SLOW}",
            [{"field": "__root__", "message": TOO_SLOW}],
        )
    return dict(zip(pending, found, strict=True))
