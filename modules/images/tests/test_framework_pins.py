"""Pins on the framework internals images reads.

The module range admits any 0.0.x framework, but these call sites read names
the framework does not promise to keep. Each test fails, naming the call site,
the moment one changes - in CI on the framework bump, not in production.

* ``sm_images/errors.py`` (``_error_page``) -
  ``simple_module_hosting._error_handlers.render_error_page`` (records pins
  the same name). No public replacement yet.
* ``sm_images/pipeline/eager_drain.py`` (``deliver_code``/``in_delivery``) -
  ``background_tasks.outbox_dispatch.deliver_one`` is the coroutine on the
  stack while a durable handler runs, and ``OutboxTransport.drain`` is what an
  eager submit waits on.
"""

from __future__ import annotations

import inspect

import pytest

_ERRORS = "sm_images/errors.py (_error_page)"
_DRAIN = "sm_images/pipeline/eager_drain.py (deliver_code / in_delivery)"


def test_render_error_page_keeps_its_name_and_signature():
    try:
        from simple_module_hosting._error_handlers import render_error_page
    except ImportError as exc:
        pytest.fail(
            f"{_ERRORS}: simple_module_hosting._error_handlers.render_error_page is gone "
            f"({exc}); console routes would fall back to JSON instead of the error page"
        )
    assert inspect.iscoroutinefunction(render_error_page), f"{_ERRORS}: no longer async"
    params = list(inspect.signature(render_error_page).parameters)
    assert params[:3] == ["request", "status_code", "message"], (
        f"{_ERRORS}: render_error_page(request, status, detail) no longer fits: {params}"
    )


def test_the_durable_delivery_hooks_still_exist():
    """Delivery is detected from the call path: ``deliver_one`` must be the
    coroutine that runs a durable handler, and the transport must offer ``drain``."""
    from background_tasks import outbox_dispatch
    from background_tasks.outbox_transport import OutboxTransport
    from sm_images.pipeline import eager_drain

    assert inspect.iscoroutinefunction(outbox_dispatch.deliver_one), _DRAIN
    assert "sub.handler(event, ctx)" in inspect.getsource(outbox_dispatch.deliver_one), (
        f"{_DRAIN}: deliver_one no longer calls the handler itself"
    )
    assert inspect.iscoroutinefunction(OutboxTransport.drain), f"{_DRAIN}: drain gone or sync"
    assert eager_drain.deliver_code() is outbox_dispatch.deliver_one.__code__, _DRAIN
