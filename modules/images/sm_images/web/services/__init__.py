"""Business logic for the Images module, and the module-scoped container.

``ImagesServices`` is stored as ``app.state.sm_images`` by
:meth:`ImagesModule.register_settings`; set once during boot, read-only after.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sm_images.core.settings import ImagesSettings

if TYPE_CHECKING:
    from sm_images.core.tenancy import TenancyMode


@dataclass
class ImagesServices:
    """Images module singletons."""

    settings: ImagesSettings
    tenancy: TenancyMode | None = None
    """Single- or multi-tenant, read off the built middleware stack in
    ``on_startup`` by :func:`sm_images.core.tenancy.configure`; ``None`` until then,
    when :func:`sm_images.core.tenancy.mode_of` detects it on demand."""
    tenant_header: str | None = None
    """The request header the host's ``TenantMiddleware`` resolves an anonymous
    caller's tenant from; ``None`` in single mode or when the host set none."""


__all__ = ["ImagesServices"]
