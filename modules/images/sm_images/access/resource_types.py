"""The resource types images declares to the framework (``register_resource_types``).

One today: ``images.collection``, so the ``sharing`` module can grant ``view``
and ``edit`` on a collection, and check the granter through the same
:data:`~sm_images.access.POLICY` every images route uses.

**The loader applies images' tenancy rule itself.** The sharing router is the
framework's: none of images' ``bind_admin`` dependencies runs in front of it,
so on a single-tenant host nothing is bound when it builds and executes the
statement (phase 2 review, P1-1). The rule is exactly the one every images
admin route applies, per request (:func:`~sm_images.tenancy.resolve_admin`):

* a tenant bound in the contextvar wins - the plain statement, which the
  framework's tenant filter scopes;
* otherwise the request being served (:mod:`sm_images.tenancy.request_context`) is
  resolved: ``request.state.tenant_id`` if something upstream set it; else
  ``default`` only when *this request* is single-tenant (``request_mode``,
  which treats a mounted child app the framework cannot answer for as multi);
  else :class:`~sm_images.errors.TenantRequired`, the 403 images' admin
  surface answers. The statement is pinned to that tenant explicitly and tagged
  past the images guard only - the framework's own scoping is not waived, so a
  strict (multi-tenant) engine still refuses it: fail closed;
* no request at all (a caller outside HTTP): ``TenantRequired``.

The boot-time mode alone is never the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from simple_module_core.resources import ResourceType, ResourceTypeRegistry
from simple_module_db.listeners import current_tenant_id
from simple_module_db.resource_policy import select_by_id

from sm_images.access import COLLECTION_RESOURCE, POLICY
from sm_images.errors import TenantRequired
from sm_images.models import Collection
from sm_images.tenancy import all_tenants, resolve_admin, valid_tenant
from sm_images.tenancy.request_context import current_request

_NO_TENANT = "no tenant is bound for this images collection lookup"


def collection_loader() -> Callable[[str], Any]:
    """A ``StatementForId`` for collections that applies the rule above."""
    by_id = select_by_id(Collection)

    def build(resource_id: str) -> Any:
        stmt = by_id(resource_id)  # ValueError for a malformed id: sharing's 404
        if valid_tenant(current_tenant_id.get()):
            return stmt
        request = current_request()
        if request is None:
            raise TenantRequired(_NO_TENANT)
        tenant = resolve_admin(request)
        return all_tenants(stmt.where(Collection.tenant_id == tenant))

    return build


def register(registry: ResourceTypeRegistry) -> None:
    registry.register(
        ResourceType(name=COLLECTION_RESOURCE, policy=POLICY, select_by_id=collection_loader())
    )
