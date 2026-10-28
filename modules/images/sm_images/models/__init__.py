"""SQLModel tables of the Images module.

Every table is imported here so ``Base.metadata`` is complete the moment anything
imports the package - Alembic autogenerate and the test harness rely on it.
"""

from __future__ import annotations

from sm_images.models._base import Base
from sm_images.models.collection import Collection
from sm_images.models.enums import (
    ImportKind,
    ItemStatus,
    JobStatus,
    LocationSource,
    PromptInputs,
    PromptScope,
    ReviewStatus,
    StepStatus,
    Visibility,
)
from sm_images.models.group import Group
from sm_images.models.image import Image
from sm_images.models.import_item import ImportItem
from sm_images.models.import_job import ImportJob
from sm_images.models.object_intent import ObjectIntent
from sm_images.models.prompt import Prompt, PromptResult
from sm_images.models.rendition import Rendition
from sm_images.models.step_run import StepRun

__all__ = [
    "Base",
    "Collection",
    "Group",
    "Image",
    "ImportItem",
    "ImportJob",
    "ImportKind",
    "ItemStatus",
    "JobStatus",
    "LocationSource",
    "ObjectIntent",
    "Prompt",
    "PromptInputs",
    "PromptResult",
    "PromptScope",
    "Rendition",
    "ReviewStatus",
    "StepRun",
    "StepStatus",
    "Visibility",
]
