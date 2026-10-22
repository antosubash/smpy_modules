"""Builders for the index-provider tests: an indexed field and a provider
that yields fixed entries.

Its own module rather than ``conftest.py`` because these are builders and not
fixtures, shared by ``test_index_provider_guards.py`` and
``test_public_shape_and_prefix.py``.
"""

from __future__ import annotations

from sm_records.index import IndexEntry

from tests.relation_helpers import field


def indexed(key: str, type_: str = "text") -> dict:
    """``relation_helpers.field`` puts its kwargs in ``options``, and
    ``indexed`` is a flag beside them."""
    return {**field(key, type_), "indexed": True}


def yielding(*entries):
    def _provider(record, rtype):
        for kind, key, value in entries:
            yield IndexEntry(kind=kind, field_key=key, value=value)

    return _provider
