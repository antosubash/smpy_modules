"""Demo-data seeder for the records module.

Five US-flavoured business types — ``company``, ``contact``, ``product``,
``store``, ``order`` — created (if missing) and populated with records
written through the real services (:mod:`sm_records.services.types`,
:mod:`sm_records.services.records`), so a seeded install looks exactly like
one built by hand: real index rows, real revisions, real relation checks.

Two ways in:

* ``python -m sm_records.cli seed [...]`` (``sm_records/cli.py``) — the
  operator-facing command, which owns the database connection.
* :func:`seed_database`, for a test or a perf harness that already has a
  ``db_state``/``settings`` pair (see ``tests/conftest.py``) and wants to
  seed in-process without shelling out.

No new dependency: :mod:`sm_records.seed.data` is inline US-flavoured value
pools, not ``faker``.
"""

from __future__ import annotations

from typing import Any

from sm_records.seed.runner import SeedSummary, run
from sm_records.settings import RecordsSettings

__all__ = ["SeedSummary", "seed_database"]


async def seed_database(
    db_state: Any,
    settings: RecordsSettings,
    *,
    records: int = 5000,
    seed: int = 42,
    reset: bool = False,
) -> SeedSummary:
    """Seed (or top up, or reset-and-reseed) the demo dataset.

    ``records`` is the *total* count across all five types, split roughly
    5% / 25% / 15% / 45% / 10% (company / contact / product / order / store)
    with a floor of one record per type. Deterministic for a given ``seed``;
    re-running without ``reset`` adds ``records`` more on top of whatever is
    already there, with fresh unique values (SKUs, emails, order numbers) —
    see ``runner.py`` for how those avoid colliding with the existing rows.
    """
    return await run(db_state, settings, records=records, seed=seed, reset=reset)
