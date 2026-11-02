"""Pins on the framework names images reads that no contract promises.

The module range admits any 0.0.x framework, but this call site reads a name
outside the framework's published contracts. The test fails, naming the call
site, the moment it changes - in CI on the framework bump, not in production.

* ``sm_images/pipeline/eager_drain.py`` (``drain_durable``) -
  ``OutboxTransport.drain`` is what an eager submit waits on. It is not part of
  the ``DurableTransport`` protocol, and ``drain_durable`` reads it with
  ``getattr``: renamed, every eager submit would silently stop waiting for its
  durable deliveries.

The four private names this file used to pin have public replacements since
framework 0.0.42 (simple_module_python#682-#685), which images now uses.
"""

from __future__ import annotations

import inspect

import pytest

_DRAIN = "sm_images/pipeline/eager_drain.py (drain_durable)"


def test_the_outbox_transport_still_offers_drain():
    from background_tasks.outbox_transport import OutboxTransport

    assert inspect.iscoroutinefunction(OutboxTransport.drain), f"{_DRAIN}: drain gone or sync"
    try:
        inspect.signature(OutboxTransport.drain).bind(None)
    except TypeError as exc:
        pytest.fail(f"{_DRAIN}: drain() now needs arguments ({exc})")
