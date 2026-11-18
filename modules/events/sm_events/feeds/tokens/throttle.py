"""A per-token request budget, in this process.

The framework's limiter keys only by IP, user or tenant, so a link fetched from many
addresses (a leaked one being tried) has no budget of its own. This window is keyed by the
SHA-256 of the *presented* string **before any lookup**, so a real token and an invented one
over the limit get the same answer: the limit tells nobody which tokens exist.

Per process (each worker keeps its own window) and bounded: an LRU of ``max_keys`` keys, so a
flood of invented tokens cannot grow it without end. Only allowed hits are recorded, so being
refused does not extend the wait.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable

__all__ = ["TokenThrottle"]


class TokenThrottle:
    def __init__(
        self,
        *,
        limit: int,
        window: float,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, presented: str) -> float | None:
        """Count one request for ``presented``: ``None`` when it may go on, else the seconds
        until it may (rounded up to a whole second, for ``Retry-After``)."""
        key = hashlib.sha256(presented.encode("utf-8", "surrogatepass")).hexdigest()
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
                while len(self._hits) > self._max_keys:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return float(max(1, math.ceil(hits[0] + self._window - now)))
            hits.append(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
