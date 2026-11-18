"""The per-token window: bounded, uniform, and not evictable by junk."""

from __future__ import annotations

from sm_events.feeds.tokens.throttle import TokenThrottle


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(limit=3, keys=4, clock=None) -> TokenThrottle:
    return TokenThrottle(limit=limit, window=60, max_keys=keys, clock=clock or Clock())


def test_limit_and_retry_after():
    clock = Clock()
    throttle = make(clock=clock)
    assert [throttle.hit("t") for _ in range(3)] == [None, None, None]
    assert throttle.hit("t") == 60.0
    clock.now += 61
    assert throttle.hit("t") is None


def test_a_refused_hit_is_not_recorded():
    clock = Clock()
    throttle = make(limit=1, clock=clock)
    assert throttle.hit("t") is None
    clock.now += 30
    assert throttle.hit("t") == 30.0
    clock.now += 30  # the first hit has aged out: the refusal did not extend the wait
    assert throttle.hit("t") is None


def test_junk_cannot_evict_a_real_tokens_window():
    throttle = make(limit=2, keys=4)
    throttle.hit("real")
    throttle.promote("real")  # the lookup found a row for it
    throttle.hit("real")
    assert throttle.hit("real") is not None
    for i in range(50):  # far more junk than the pool holds
        throttle.hit(f"junk-{i}")
    assert throttle.hit("real") is not None  # still limited


def test_junk_is_still_limited_while_it_stays_in_the_pool():
    """An invented token over the limit is refused like a real one (the limit names nobody)."""
    throttle = make(limit=2, keys=4)
    assert [throttle.hit("junk") for _ in range(2)] == [None, None]
    assert throttle.hit("junk") is not None


def test_promotion_keeps_the_hits_already_counted():
    throttle = make(limit=3, keys=4)
    throttle.hit("real")
    throttle.hit("real")
    throttle.promote("real")
    assert throttle.hit("real") is None
    assert throttle.hit("real") is not None  # three in all, across the promotion


def test_real_pool_is_bounded_too():
    throttle = make(limit=1, keys=2)
    for name in ("a", "b", "c"):
        throttle.hit(name)
        throttle.promote(name)
    assert throttle.hit("c") is not None
    assert throttle.hit("a") is None  # the oldest real window was the one evicted


def test_nothing_plain_is_kept():
    throttle = make()
    throttle.hit("evf_secret")
    assert "evf_secret" not in repr(vars(throttle))
