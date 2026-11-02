"""The pipeline runtime and tenant a request-time launch needs (restart, regroup)."""

from __future__ import annotations

from simple_module_db.listeners import current_tenant_id

from sm_images.core.errors import ServiceUnavailable
from sm_images.pipeline.runtime import Runtime, current_runtime

__all__ = ["runtime", "tenant"]


def runtime() -> Runtime:
    found = current_runtime()
    if found is None:
        raise ServiceUnavailable("the image pipeline is not running in this process")
    return found


def tenant() -> str:
    bound = current_tenant_id.get()
    if bound is None:  # bind_admin ran first; this is the executor's own guard
        raise ServiceUnavailable("no tenant is bound")
    return bound
