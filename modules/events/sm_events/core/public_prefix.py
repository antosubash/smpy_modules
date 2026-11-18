"""The public prefix an operator typed, made usable or refused.

Read once, in ``on_startup``, from the hydrated settings. The settings class has no
validators on purpose (one bad stored value would reset every field), so a value that
cannot be served is handled here: logged, and ``/events`` is served instead.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection

from sm_events.core import constants

__all__ = ["effective"]

logger = logging.getLogger(__name__)

_PATTERN = re.compile(constants.PUBLIC_PREFIX_PATTERN)


def effective(value: str | None, *, taken: Collection[str] = ()) -> str:
    """``value`` as a prefix with a leading slash and none trailing, or ``/events``.

    ``taken`` holds first path segments something else already owns (another module's
    prefix, a content locale): the framework's own are always refused."""
    normalised = (value or "").strip().strip("/")
    first = normalised.split("/", 1)[0]
    refused = (
        not _PATTERN.fullmatch(normalised)
        or first in constants.RESERVED_PREFIX_SEGMENTS
        or first in taken
    )
    if refused:
        logger.error(
            "events: public_prefix %r is not usable, serving at %s",
            value,
            constants.DEFAULT_PUBLIC_PREFIX,
        )
        return constants.DEFAULT_PUBLIC_PREFIX
    return f"/{normalised}"
