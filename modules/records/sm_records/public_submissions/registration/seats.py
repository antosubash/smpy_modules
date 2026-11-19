"""The one seam between a record's life and its seat (PR 9).

Every path that trashes, restores or purges a record of a registration type calls the matching
hook here, **inside the same transaction and after the records locks it already holds**, so a
record and its seat change together or not at all. The global lock order, in one line, for every
path (submit, cancel, trash, restore, purge, retention, reconciliation)::

    records address/opt-in locks -> records type lock -> records row lock
        -> events event row (FOR SHARE) -> events counter row -> events seat rows

and events never takes a records lock (its calls into records, the provider's, run on their own
connection and only read). Each hook is a no-op unless the type's kind is ``registration``, and,
without the events module, a trash or purge just carries on (nothing holds a seat to free).

The events integration is imported inside each function: nothing of events is imported with this
module.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from sm_records.contracts.public_submissions import KIND_REGISTRATION

__all__ = ["available", "integration", "is_registration"]

logger = logging.getLogger(__name__)
_WARNED = {"missing": False}


def is_registration(rtype: Any) -> bool:
    return ((getattr(rtype, "public_submissions", None) or {}).get("kind")) == KIND_REGISTRATION


def integration() -> Any:
    """The events integration module; ``ImportError`` when events is not installed."""
    return importlib.import_module("sm_records.integrations.events.registration")


def available() -> bool:
    """Whether the events module (and so seats) is installed."""
    try:
        integration()
    except ImportError:
        if not _WARNED["missing"]:
            _WARNED["missing"] = True
            logger.info("records: the events module is not installed; registrations hold no seats")
        return False
    return True
