"""What the last verify found, so the health check can say it out loud.

Design §7.5's objection to a maintained aggregate was that it is a second
source of truth and can drift. Phase 5 §5.2 answers it with a verifier rather
than a denial — but a verifier nobody runs, or whose output scrolls past in a
terminal, is not an answer either. So the result of the last verify is kept
here, and :mod:`sm_records.health` turns it into a ``reduce_drift`` detail on
``/health/ready``.

**In process, deliberately not in the database.** Storing it would make the
drift record itself a third thing to keep in step, and a stale "this drifted
once" row outliving the rebuild that fixed it is worse than no row at all. The
cost is the honest one and the README says it: a verify run by the CLI is a
*different process* from the server, so it degrades that process's health
check and not the running host's. A verify run in-process — from the reindex
the host schedules — is what reaches the live check.

Cleared by a clean verify of the type, and by a rebuild of it, because both
mean the stored rows now agree with the records.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the annotation
    from sm_records.index.reduce_rebuild import Drift

_drift: dict[int, dict[str, int]] = {}
"""``{type id: {reduce key: number of groups that disagree}}``. Group counts
rather than the groups themselves: a health detail is one line, and a spec
that drifted in ten thousand groups must not print ten thousand of them."""


def record_drift(type_id: int, drifts: Iterable[Drift]) -> None:
    """Replace what is known about one type. An empty ``drifts`` clears it —
    a clean verify is not "no news", it is positive evidence."""
    counts: dict[str, int] = {}
    for drift in drifts:
        counts[drift.key] = counts.get(drift.key, 0) + 1
    if counts:
        _drift[type_id] = counts
    else:
        _drift.pop(type_id, None)


def clear_drift(type_id: int | None = None) -> None:
    """Forget one type's drift, or all of it — what a rebuild does."""
    if type_id is None:
        _drift.clear()
    else:
        _drift.pop(type_id, None)


def current_drift() -> dict[int, dict[str, int]]:
    return {type_id: dict(keys) for type_id, keys in _drift.items()}


def drift_detail() -> str | None:
    """The health check's sentence, or ``None`` when nothing is known to have
    drifted. Type *ids* and not keys: this module never holds a session, and a
    detail that had to read the database to name a type would be a health
    check that fails when the database is down for an unrelated reason."""
    if not _drift:
        return None
    parts = [
        f"type {type_id} ({', '.join(f'{key}: {n} group(s)' for key, n in sorted(keys.items()))})"
        for type_id, keys in sorted(_drift.items())
    ]
    return (
        "reduce index disagrees with the records for " + "; ".join(parts) + " — run "
        "`python -m sm_records.cli reindex --type KEY` to rebuild, then "
        "`reindex --verify` to confirm"
    )
