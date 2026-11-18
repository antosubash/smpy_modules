"""Keep a feed token out of every log line (Ruling 12).

The token is a path segment, and the framework logs paths: ``RequestLoggingMiddleware`` passes
``path`` as an ``extra`` at INFO, the rate limiter prints it on a 429, and uvicorn's access line
carries it. A :class:`Filter` on each of those loggers rewrites ``/feed/<anything>`` to
``/feed/<redacted>`` in the rendered message (its arguments are rendered into it), in every
string attribute of the record (the ``extra`` ``path`` among them) and in a traceback, and
scrubs anything shaped like a token wherever it appears, which covers an exception message that
quotes the address.

Not covered: a proxy or load balancer in front of the process logs paths itself; the operations
doc tells operators to redact ``/feed/`` there too.

:func:`install` is idempotent and runs first in ``EventsModule.on_startup``.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Final

from sm_events.core import constants

__all__ = ["LOGGERS", "REDACTED", "Filter", "install", "redact"]

LOGGERS: Final = (
    "simple_module.request",
    "simple_module.request_guard",
    "uvicorn.access",
    "uvicorn.error",
)
"""The request log, the rate limiter's and body limit's (one logger), and uvicorn's two."""
REDACTED: Final = "<redacted>"

_SEGMENT: Final = re.compile(rf'(/{constants.FEED_PATH_SEGMENT}/)[^/?#\s"\']+')
_SHAPE: Final = re.compile(rf"{re.escape(constants.TOKEN_PREFIX)}[A-Za-z0-9_-]{{20,}}")
_STANDARD: Final = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


def redact(text: str) -> str:
    """``text`` with the segment after ``/feed/`` and any token-shaped string replaced."""
    if constants.TOKEN_PREFIX not in text and f"/{constants.FEED_PATH_SEGMENT}/" not in text:
        return text
    return _SHAPE.sub(REDACTED, _SEGMENT.sub(rf"\1{REDACTED}", text))


class Filter(logging.Filter):
    """Redacts the message, its arguments, the record's string attributes and its traceback."""

    @staticmethod
    def _message(record: logging.LogRecord) -> None:
        """Redact the *rendered* message, never the template: rewriting ``/feed/%s.ics`` would
        eat its placeholder and break formatting. A message that holds nothing to hide is left
        exactly as it was; one that does becomes its redacted text with no arguments."""
        try:
            rendered = record.getMessage()
        except Exception:  # a malformed record: the handler will report it, not leak it
            rendered = str(record.msg)
        cleaned = redact(rendered)
        if cleaned != rendered or redact(str(record.msg)) != str(record.msg):
            record.msg, record.args = cleaned, ()

    def filter(self, record: logging.LogRecord) -> bool:
        self._message(record)
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD and isinstance(value, str):
                setattr(record, key, redact(value))
        if record.exc_info and not record.exc_text:
            # The handler would render this later from the live exception, message and all.
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install() -> None:
    """Attach one :class:`Filter` to each of :data:`LOGGERS` (idempotent)."""
    for name in LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, Filter) for f in target.filters):
            target.addFilter(Filter())
