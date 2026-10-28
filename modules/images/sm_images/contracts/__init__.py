"""What other modules may import from images (spec §7).

Events, the read-only schemas and the policy-filtered reads. Nothing else in
``sm_images`` is a stable surface. ``points`` joins in Task 26 (it needs the
map tables).
"""

from __future__ import annotations

from sm_images.contracts.events import (
    CollectionDeleted,
    CollectionVisibilityChanged,
    ImageAdded,
)
from sm_images.contracts.reads import get_collection, list_collections, rendition_url
from sm_images.contracts.schemas import CollectionPageRead, CollectionRead, ImageRead
from sm_images.pipeline.extensions import load_extensions
from sm_images.pipeline.presets import Preset, PromptSpec
from sm_images.pipeline.registry import (
    CyclicRequiresError,
    DuplicateStepError,
    RegistryFrozenError,
    ReservedStepIdError,
    TooManyDisplayMutators,
    UnresolvedRequiresError,
    all_steps,
    get_preset,
    get_step,
    register_preset,
    register_step,
)
from sm_images.pipeline.step import DisplayNotAllowed, Step, StepContext, StepOutcome

__all__ = [
    "CollectionDeleted",
    "CollectionPageRead",
    "CollectionRead",
    "CollectionVisibilityChanged",
    "CyclicRequiresError",
    "DisplayNotAllowed",
    "DuplicateStepError",
    "ImageAdded",
    "ImageRead",
    "Preset",
    "PromptSpec",
    "RegistryFrozenError",
    "ReservedStepIdError",
    "Step",
    "StepContext",
    "StepOutcome",
    "TooManyDisplayMutators",
    "UnresolvedRequiresError",
    "all_steps",
    "get_collection",
    "get_preset",
    "get_step",
    "list_collections",
    "load_extensions",
    "register_preset",
    "register_step",
    "rendition_url",
]
