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

The six names below are the whole promise. Everything else in this package —
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
from sm_records.schema.types import IndexKind

__all__ = [
    "IndexEntry",
    "IndexKind",
    "IndexProvider",
    "VirtualField",
    "register_index_provider",
    "virtual_fields",
]
