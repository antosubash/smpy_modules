"""Keep a confirm, unsubscribe or cancel token out of every log line.

The landing pages under ``/records/submissions/`` carry their token in the query (``?t=<token>``),
and the framework logs paths with their query: the request logger passes ``path`` as an ``extra``
at INFO, the rate limiter prints it on a 429 and uvicorn's access line carries it. A :class:`Filter`
on each of those loggers (and on every handler that exists) rewrites the ``t`` value to
``<redacted>`` in the rendered message, its arguments, every string attribute of the record and a
traceback. This is a copy of the approach events' private-feed tokens use (records may not import
events' code); the POST routes carry the token in the body, which is never logged.

Not covered: a proxy or load balancer in front of the process logs paths itself and must redact the
``t`` query of ``/records/submissions/`` too.

:func:`install` is idempotent and runs in ``RecordsModule.on_startup``.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Any, Final

from sm_records.core import constants

__all__ = ["LOGGERS", "REDACTED", "Filter", "install", "redact"]

LOGGERS: Final = (
    "simple_module.request",
    "simple_module.request_guard",
    "uvicorn.access",
    "uvicorn.error",
)
REDACTED: Final = "<redacted>"

_PAGES: Final = re.escape(constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX)
_QUERY: Final = re.compile(rf"({_PAGES}[a-z-]+\?(?:[^\s\"'#]*?&)?t=)[^&\s\"'#]+")
_STANDARD: Final = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


def redact(text: str) -> str:
    """``text`` with the token of any ``/records/submissions/<page>?t=...`` replaced."""
    return _QUERY.sub(rf"\1{REDACTED}", text)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, tuple):
        return tuple(_clean(v) for v in value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


class Filter(logging.Filter):
    """Redacts the message, its arguments, the record's string attributes and its traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple | dict) and record.args:
            record.args = _clean(record.args)  # keep the shape: uvicorn's line unpacks exactly five
        try:
            rendered = record.getMessage()
        except Exception:  # a malformed record: the handler reports it, not us
            rendered = str(record.msg)
        cleaned = redact(rendered)
        if cleaned != rendered or redact(str(record.msg)) != str(record.msg):
            record.msg, record.args = cleaned, ()
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD:
                setattr(record, key, _clean(value))
        if record.exc_info and not record.exc_text:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def _handlers() -> list[logging.Handler]:
    loggers = [
        logging.getLogger(),
        *(v for v in logging.root.manager.loggerDict.values() if isinstance(v, logging.Logger)),
    ]
    return list({id(h): h for target in loggers for h in target.handlers}.values())


def install() -> None:
    """Attach one :class:`Filter` to each of :data:`LOGGERS` and to every handler that exists."""
    for name in LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, Filter) for f in target.filters):
            target.addFilter(Filter())
    for handler in _handlers():
        if not any(isinstance(f, Filter) for f in handler.filters):
            handler.addFilter(Filter())
