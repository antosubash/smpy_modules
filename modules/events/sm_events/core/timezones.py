"""IANA timezone names: which are known, and the fallback for one that is not."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Final
from zoneinfo import available_timezones

logger = logging.getLogger(__name__)

FALLBACK: Final = "UTC"

_warned: set[str] = set()


@lru_cache(maxsize=1)
def _known() -> frozenset[str]:
    return frozenset(available_timezones())


def is_known(name: str) -> bool:
    """Is ``name`` an IANA timezone this host knows? Case matters."""
    return name in _known()


def effective(name: str | None) -> str:
    """``name`` when it is known, else ``UTC`` (one warning per unknown name)."""
    if not name:
        return FALLBACK
    if is_known(name):
        return name
    if name not in _warned:
        _warned.add(name)
        logger.warning("unknown timezone %r; using %s", name, FALLBACK)
    return FALLBACK
