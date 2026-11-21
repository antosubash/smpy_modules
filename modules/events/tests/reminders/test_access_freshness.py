"""How fresh a reminder's access check can be: the bound the docs state.

A reminder's recipient is checked at send time through the worker's headless app. The framework's
direct-grant source caches per user for ``GRANTS_TTL_SECONDS`` and the worker has no invalidation
(only a request in the web process clears its own app's cache), so a direct ``events.*`` grant
revoked elsewhere can still allow a reminder for that long. Role changes are replayed from the
permissions module once per tick. ``docs/reminders.md`` says both; this pins the constant so a
framework change is noticed and the doc revisited."""

from __future__ import annotations

from pathlib import Path

from permissions.grants import source

DOC = (Path(__file__).resolve().parents[2] / "docs" / "reminders.md").read_text(encoding="utf-8")


def test_the_direct_grant_cache_is_thirty_seconds():
    assert source.GRANTS_TTL_SECONDS == 30, "the framework changed the bound: update reminders.md"


def test_the_doc_states_the_bound_in_words():
    assert "up to 30 s" in DOC and "one tick" in DOC
