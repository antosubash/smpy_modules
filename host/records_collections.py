"""Record **collections** this host declares — Phase 5 §6.1.

A collection gives one Record Type its own document, revision and index tables
instead of sharing the global ones. The tables have to exist in this host's
Alembic history, so a collection cannot be a database-backed setting read at
boot: it is declared here, in code, and this module is imported by ``main.py``
**before** ``create_app`` — the records module seals the registry in its first
hook, and a declaration after that point would create tables no migration ever
wrote.

``events`` is the demo host's one collection, and it is what the repo's
``event`` demo type is created in (``sm_records.seed``). It is also the
integration test for the feature: every records screen in this app is served
against a host that declares a collection, so a regression in the table-set
seam shows up as a broken page here rather than only in a unit test.

A host that wants none of this deletes this file and its import. What it then
runs is exactly the Phase 4 code paths against exactly the Phase 4 tables
(§6.5) — and the ``records_c_events_*`` migration can be skipped along with it.
"""

from __future__ import annotations

from sm_records.collections import declare_collection

declare_collection("events")
