"""What an import may do with an item its source marked private (``CLASS:PRIVATE``).

One policy for the preview and the write, so the two can never disagree:

* a **new** private item is created as a draft, even when the import is applied as published
  (Ruling 25: a public calendar would otherwise publish what was marked not-for-everyone);
* an **update** from a private item may change a draft, but never a published or scheduled event:
  that would write content the source marked private into something visitors can (or soon will)
  see, and the plan's rule that an update never publishes or unpublishes rules out the quiet
  alternatives. The item is skipped, ``private_kept``, and the event is left exactly as it was.
  (The plan is silent on updates; this is the module's ruling.)

An item that *was* private and no longer is follows the normal update rule: the policy looks only
at the item being imported now.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

__all__ = ["PRIVATE_KEPT", "publish_new", "update_refused"]

PRIVATE_KEPT: Final = "private_kept"


def publish_new(*, private: bool, requested: bool, may_publish: bool) -> bool:
    """Whether a new event is created published: asked for, allowed, and not private."""
    return requested and may_publish and not private


def update_refused(*, private: bool, status: str, publish_at: datetime | None) -> bool:
    """Whether a private item must not be written into an existing event in this state."""
    return private and (status == "published" or publish_at is not None)
