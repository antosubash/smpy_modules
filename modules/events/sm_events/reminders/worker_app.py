"""The worker runtime (PR 8, Task 9). Until it lands, a worker is not supported.

A Celery worker builds no app, so it has no user directory, no membership store and no
permission registry: it cannot tell whether someone may still see an event
(simple_module_python #1005). Until a worker runtime proves it grants exactly what a request
principal holds, :func:`worker_runtime_supported` says no, and reminders report
``worker_access_unavailable`` instead of promising mail that could be sent to someone who lost
access.
"""

from __future__ import annotations

__all__ = ["worker_runtime_supported"]


def worker_runtime_supported() -> bool:
    return False
