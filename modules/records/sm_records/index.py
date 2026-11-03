"""Public index-provider extension API."""

from sm_records.records.index import (
    IndexEntry,
    IndexKind,
    IndexProvider,
    ReduceSpec,
    VirtualField,
    register_index_provider,
    register_reduce_provider,
    virtual_fields,
)
from sm_records.records.index import __all__ as __all__
