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

from sm_records.seed.runner import SeedSummary, seed_database

__all__ = ["SeedSummary", "seed_database"]
