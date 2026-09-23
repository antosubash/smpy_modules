"""Business logic for the Records module, and the module-scoped container.

``RecordsServices`` lives in this package's ``__init__`` rather than a sibling
``services.py``: Python resolves ``sm_records.services`` to the package, so a
same-named module beside it is unreachable. Stored as ``app.state.sm_records``
by :meth:`RecordsModule.register_settings`; set once during boot, read-only
after.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sm_records.settings import RecordsSettings

if TYPE_CHECKING:
    from sm_records.media import MediaApi
    from sm_records.tenancy import TenancyMode


@dataclass
class RecordsServices:
    """Records module singletons."""

    settings: RecordsSettings
    media_api: MediaApi | None = None
    """The media library the ``media`` field picker talks to, resolved once in
    ``on_startup`` by :func:`sm_records.media.configure`; ``None`` until then,
    and afterwards on a host that has none."""
    tenancy: TenancyMode | None = None
    """Single- or multi-tenant, read off the built middleware stack in
    ``on_startup`` by :func:`sm_records.tenancy.configure`; ``None`` until then,
    when :func:`sm_records.tenancy.mode_of` detects it on demand."""


__all__ = ["RecordsServices"]
