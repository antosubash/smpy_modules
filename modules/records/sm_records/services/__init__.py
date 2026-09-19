"""Business logic for the Records module, and the module-scoped container.

``RecordsServices`` lives in this package's ``__init__`` rather than a sibling
``services.py``: Python resolves ``sm_records.services`` to the package, so a
same-named module beside it is unreachable. Stored as ``app.state.sm_records``
by :meth:`RecordsModule.register_settings`; set once during boot, read-only
after.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_records.settings import RecordsSettings


@dataclass
class RecordsServices:
    """Records module singletons."""

    settings: RecordsSettings


__all__ = ["RecordsServices"]
