"""SQLModel tables of the Newsletter module.

Every table is imported here so ``Base.metadata`` is complete the moment anything
imports the package - Alembic autogenerate and the test harness rely on it.
"""

from __future__ import annotations

from sm_newsletter.models._base import Base
from sm_newsletter.models.campaign import Campaign
from sm_newsletter.models.dispatch_lock import DispatchLock
from sm_newsletter.models.imports import ImportEntry, ImportJob
from sm_newsletter.models.link import Click, Link
from sm_newsletter.models.render import CampaignRender
from sm_newsletter.models.segment import Segment
from sm_newsletter.models.send import Send, SendAttempt
from sm_newsletter.models.suppression import Suppression, SuppressionLift

__all__ = [
    "Base",
    "Campaign",
    "CampaignRender",
    "Click",
    "DispatchLock",
    "ImportEntry",
    "ImportJob",
    "Link",
    "Segment",
    "Send",
    "SendAttempt",
    "Suppression",
    "SuppressionLift",
]
