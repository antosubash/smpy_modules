"""What other modules may import from images (spec §7).

Events, the read-only schemas and the policy-filtered reads (``points`` among
them: a collection's map as GeoJSON). Nothing else in ``sm_images`` is a
stable surface.
"""

from __future__ import annotations

from sm_images.ai.reads import GroupMemberRead, GroupRead, PromptResultRead
from sm_images.contracts.events import (
    CollectionDeleted,
    CollectionVisibilityChanged,
    ImageAdded,
    ImageProcessed,
    PromptResultReviewed,
)
from sm_images.contracts.reads import get_collection, list_collections, points, rendition_url
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
from sm_images.pipeline.step import (
    DisplayNotAllowed,
    DisplayWriterMissing,
    Step,
    StepContext,
    StepOutcome,
)

__all__ = [
    "CollectionDeleted",
    "CollectionPageRead",
    "CollectionRead",
    "CollectionVisibilityChanged",
    "CyclicRequiresError",
    "DisplayNotAllowed",
    "DisplayWriterMissing",
    "DuplicateStepError",
    "GroupMemberRead",
    "GroupRead",
    "ImageAdded",
    "ImageProcessed",
    "ImageRead",
    "Preset",
    "PromptResultRead",
    "PromptResultReviewed",
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
    "points",
    "register_preset",
    "register_step",
    "rendition_url",
]
