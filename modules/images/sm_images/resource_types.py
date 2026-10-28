"""The resource types images declares to the framework (``register_resource_types``).

One today: ``images.collection``, so the ``sharing`` module can grant ``view``
and ``edit`` on a collection, and check the granter through the same
:data:`~sm_images.access.POLICY` every images route uses.
"""

from __future__ import annotations

from simple_module_core.resources import ResourceType, ResourceTypeRegistry
from simple_module_db.resource_policy import select_by_id

from sm_images.access import COLLECTION_RESOURCE, POLICY
from sm_images.models import Collection


def register(registry: ResourceTypeRegistry) -> None:
    registry.register(
        ResourceType(name=COLLECTION_RESOURCE, policy=POLICY, select_by_id=select_by_id(Collection))
    )
