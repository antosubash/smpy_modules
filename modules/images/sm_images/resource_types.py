"""The resource types images declares to the framework (``register_resource_types``).

One today: ``images.collection``, so the ``sharing`` module can grant ``view``
and ``edit`` on a collection, and check the granter through the same
:data:`~sm_images.access.POLICY` every images route uses.

**The loader binds images' tenancy rule itself.** The sharing router is the
framework's: none of images' ``bind_admin`` dependencies runs in front of it,
so on a single-tenant host nothing is bound when it builds and executes the
statement (phase 2 review, P1-1). The rule is the one ``resolve_admin``
applies, read without a request:

* a tenant something upstream bound (the framework's ``TenantMiddleware`` on
  a multi-tenant host, or a parent app) always wins - the plain statement,
  which the framework's tenant filter scopes;
* nothing bound and the host is single-tenant - the statement pinned
  explicitly to :data:`~sm_images.tenancy.DEFAULT_TENANT` and tagged past the
  images guard. It does **not** waive the framework's own scoping, so on a
  strict (multi-tenant) engine - a child app mis-detected as single - the
  framework still refuses it: fail closed;
* nothing bound and the host is multi-tenant, or the mode is not known yet
  (``on_startup`` has not run) - :class:`~sm_images.errors.TenantRequired`,
  the 403 images' admin surface answers.
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
from sm_images.tenancy import DEFAULT_TENANT, TenancyMode, all_tenants, valid_tenant

ModeSource = Callable[[], TenancyMode | None]

_NO_TENANT = (
    "no organisation is active for this account; pick one before sharing an images collection"
)


def collection_loader(mode: ModeSource) -> Callable[[str], Any]:
    """A ``StatementForId`` for collections that applies the rule above."""
    by_id = select_by_id(Collection)

    def build(resource_id: str) -> Any:
        stmt = by_id(resource_id)  # ValueError for a malformed id: sharing's 404
        if valid_tenant(current_tenant_id.get()):
            return stmt
        if mode() is TenancyMode.SINGLE:
            return all_tenants(stmt.where(Collection.tenant_id == DEFAULT_TENANT))
        raise TenantRequired(_NO_TENANT)

    return build


def register(registry: ResourceTypeRegistry, mode: ModeSource) -> None:
    """``mode`` answers the host's tenancy mode as images detected it at startup."""
    registry.register(
        ResourceType(name=COLLECTION_RESOURCE, policy=POLICY, select_by_id=collection_loader(mode))
    )
