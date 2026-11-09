"""Public index extension API."""

from sm_records.records.index import (
    IndexEntry as IndexEntry,
)
from sm_records.records.index import (
    IndexKind as IndexKind,
)
from sm_records.records.index import (
    IndexProvider as IndexProvider,
)
from sm_records.records.index import (
    ReduceSpec as ReduceSpec,
)
from sm_records.records.index import (
    VirtualField as VirtualField,
)
from sm_records.records.index import __all__ as __all__
from sm_records.records.index import (
    register_index_provider as register_index_provider,
)
from sm_records.records.index import (
    register_reduce_provider as register_reduce_provider,
)
from sm_records.records.index import (
    virtual_fields as virtual_fields,
)

# This path was a package before 0.0.14: its old submodules resolve through
# core/moved_paths until 0.0.17 (#319), and a submodule import needs a __path__.
__path__: list[str] = []
