"""The index layer, and the extension point it publishes (design doc §7.6).

A host module that wants a record queryable by something the schema does not
express — a computed bucket, a normalised sort key, a value denormalised from
a related record — registers an index provider and the virtual fields it
projects::

    from sm_records.index import IndexEntry, IndexKind, VirtualField
    from sm_records.index import register_index_provider

    def price_bucket(record, rtype):
        price = (record.data or {}).get("price")
        if price is not None:
            yield IndexEntry(IndexKind.NUMBER, "price_bucket", int(float(price)) // 100)

    register_index_provider(
        price_bucket, fields=[VirtualField("price_bucket", IndexKind.NUMBER)]
    )

A **reduce provider** is the other half, added in Phase 5 §5.2: an aggregate
maintained on write rather than a row per record, for a volume where the live
``GROUP BY`` behind ``GET …/records/aggregate`` is too slow::

    from decimal import Decimal

    from sm_records.index import ReduceSpec, register_reduce_provider

    register_reduce_provider(ReduceSpec(
        key="orders_per_state",
        group_by=lambda record, rtype: (record.data or {}).get("ship_state"),
        value=lambda record, rtype: Decimal((record.data or {}).get("total") or 0),
    ))

Read it back with ``?reduce=orders_per_state`` on that same endpoint, rebuild
it with ``python -m sm_records.cli reindex``, and check it with
``reindex --verify``. The maintained rows are a second source of truth, so the
verifier is not optional decoration — see the README.

The eight names below are the whole promise. Everything else in this package —
the writer, the filter grammar, the rebuild — is internal and moves between
releases; import it and a patch release may break you.
"""

from __future__ import annotations

from sm_records.index.providers import (
    IndexEntry,
    IndexProvider,
    VirtualField,
    virtual_fields,
)
from sm_records.index.providers import register as register_index_provider
from sm_records.index.reduce import ReduceSpec, register_reduce_provider
from sm_records.schema.types import IndexKind

__all__ = [
    "IndexEntry",
    "IndexKind",
    "IndexProvider",
    "ReduceSpec",
    "VirtualField",
    "register_index_provider",
    "register_reduce_provider",
    "virtual_fields",
]
