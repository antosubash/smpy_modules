"""Performance suite for the records module.

Marked ``perf`` and excluded from the default run (``addopts`` in
``modules/records/pyproject.toml``). Run it with::

    cd modules/records && uv run pytest -m perf tests/perf

Size is set by ``RECORDS_PERF_N`` (default 2000) and the repetition count by
``RECORDS_PERF_REPS`` (default 20); ``RECORDS_PERF_DB`` points the whole suite
at an already-seeded SQLite file instead of seeding a fresh one.
"""
