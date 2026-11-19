"""A per-token request budget, in this process.

The framework's limiter keys only by IP, user or tenant, so a link fetched from many
addresses (a leaked one being tried) has no budget of its own. This window is keyed by the
SHA-256 of the *presented* string **before any lookup**, so a real token and an invented one
over the limit get the same answer: the limit tells nobody which tokens exist.

**Per process**: each worker keeps its own windows, so the real budget is ``limit`` times the
number of workers. The per-IP limit is the bound that matters.

Two bounded LRUs of ``max_keys`` each. A presented string starts in the *junk* pool; once a feed was
actually **served** for it, :meth:`promote` moves its window to the *real* pool (a refused row,
revoked or otherwise, stays junk, so it is indistinguishable from an invented token). A flood of
invented tokens can therefore only evict other junk, never a real token's window, and an
invented token over the limit is still refused exactly as a real one. Only allowed hits are
recorded, so being refused does not extend the wait. Only digests are kept.
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
        self._junk: OrderedDict[str, deque[float]] = OrderedDict()
        self._real: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(presented: str) -> str:
        return hashlib.sha256(presented.encode("utf-8", "surrogatepass")).hexdigest()

    def _touch(self, pool: OrderedDict[str, deque[float]], key: str) -> deque[float]:
        hits = pool.get(key)
        if hits is None:
            hits = pool[key] = deque()
            while len(pool) > self._max_keys:
                pool.popitem(last=False)
        else:
            pool.move_to_end(key)
        return hits

    def hit(self, presented: str) -> float | None:
        """Count one request for ``presented``: ``None`` when it may go on, else the seconds
        until it may (rounded up to a whole second, for ``Retry-After``)."""
        key = self._key(presented)
        now = self._clock()
        with self._lock:
            hits = self._touch(self._real if key in self._real else self._junk, key)
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return float(max(1, math.ceil(hits[0] + self._window - now)))
            hits.append(now)
            return None

    def promote(self, presented: str) -> None:
        """A feed was served for ``presented``: keep its window in the pool junk cannot evict
        from."""
        key = self._key(presented)
        with self._lock:
            if key in self._real:
                return
            hits = self._junk.pop(key, None)
            self._touch(self._real, key).extend(hits or ())

    def clear(self) -> None:
        with self._lock:
            self._junk.clear()
            self._real.clear()
