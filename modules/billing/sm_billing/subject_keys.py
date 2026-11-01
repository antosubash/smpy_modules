"""The subject-key builders with no dependencies, so ``contracts`` can export them.

``sm_billing.subjects`` re-exports these; it imports the error and model
layers, which import ``contracts`` themselves.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sm_billing import constants as c

SubjectKind = Literal["tenant", "user"]


def subject_for_tenant(tenant_id: str) -> str:
    return tenant_id


def subject_for_user(user_id: str | uuid.UUID) -> str:
    return f"{c.USER_SUBJECT_PREFIX}{user_id}"


def subject_mode(app: Any) -> SubjectKind:
    """The mode ``on_startup`` stored on ``app.state`` (tenant when unset)."""
    return getattr(app.state, c.SUBJECTS_STATE_ATTR, c.SUBJECT_MODE_TENANT)
