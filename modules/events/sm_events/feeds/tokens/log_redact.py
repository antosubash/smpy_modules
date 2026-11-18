"""Keep a feed token out of every log line (Ruling 12).

The token is a path segment, and the framework logs paths: ``RequestLoggingMiddleware`` passes
``path`` as an ``extra`` at INFO, the rate limiter prints it on a 429, and uvicorn's access line
carries it. A :class:`Filter` on each of those loggers rewrites ``/feed/<anything>`` to
``/feed/<redacted>`` in the rendered message (its arguments are rendered into it), in every
string attribute of the record (the ``extra`` ``path`` among them) and in a traceback, and
scrubs anything shaped like a token wherever it appears, which covers an exception message that
quotes the address. A SHA-256 digest (what the token lookup binds) is scrubbed only from the two
database loggers' records.

Not covered: a proxy or load balancer in front of the process logs paths itself; the operations
doc tells operators to redact ``/feed/`` there too.

:func:`install` is idempotent and runs first in ``EventsModule.on_startup``.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Any, Final

from sm_events.core import constants

__all__ = ["LOGGERS", "REDACTED", "Filter", "install", "redact"]

LOGGERS: Final = (
    "simple_module.request",
    "simple_module.request_guard",
    "uvicorn.access",
    "uvicorn.error",
    "aiosqlite",
    "sqlalchemy.engine.Engine",
)
"""The request log, the rate limiter's and body limit's (one logger), uvicorn's two, and the
two database loggers that print a statement's parameters (``aiosqlite`` at DEBUG, SQLAlchemy's
engine when ``echo`` is on): the digest the lookup binds must not reach them either."""
REDACTED: Final = "<redacted>"

_SEGMENT: Final = re.compile(rf'(/{constants.FEED_PATH_SEGMENT}/)[^/?#\s"\']+')
_SHAPE: Final = re.compile(rf"{re.escape(constants.TOKEN_PREFIX)}[A-Za-z0-9_-]{{20,}}")
_DIGEST: Final = re.compile(rf"(?<![0-9a-f])[0-9a-f]{{{constants.TOKEN_HASH_LENGTH}}}(?![0-9a-f])")
"""A SHA-256 hex digest: what the hash lookup binds. Scrubbed only from the two database loggers'
records (where a statement's parameters print); another module's 64-hex checksum in its own log
line is left alone."""
_STANDARD: Final = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


_DIGEST_LOGGERS: Final = ("aiosqlite", "sqlalchemy.engine")


def redact(text: str, *, digests: bool = True) -> str:
    """``text`` with the segment after ``/feed/`` and any token-shaped string replaced, and, with
    ``digests``, any SHA-256 digest too (only for the database loggers: see :class:`Filter`)."""
    text = _SEGMENT.sub(rf"\1{REDACTED}", text)
    text = _SHAPE.sub(REDACTED, text)
    return _DIGEST.sub(REDACTED, text) if digests else text


def _clean(value: Any, digests: bool) -> Any:
    """``value`` with every string in it redacted; other types are left as they are."""
    if isinstance(value, str):
        return redact(value, digests=digests)
    if isinstance(value, tuple):
        return tuple(_clean(v, digests) for v in value)
    if isinstance(value, list):
        return [_clean(v, digests) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v, digests) for k, v in value.items()}
    return value


class Filter(logging.Filter):
    """Redacts the message, its arguments, the record's string attributes and its traceback."""

    @staticmethod
    def _message(record: logging.LogRecord, digests: bool) -> None:
        """Redact the *rendered* message, never the template: rewriting ``/feed/%s.ics`` would
        eat its placeholder and break formatting. A message that holds nothing to hide is left
        exactly as it was; one that does becomes its redacted text with no arguments."""
        try:
            rendered = record.getMessage()
        except Exception:  # a malformed record: the handler will report it, not leak it
            rendered = str(record.msg)
        cleaned = redact(rendered, digests=digests)
        if cleaned != rendered or redact(str(record.msg), digests=digests) != str(record.msg):
            record.msg, record.args = cleaned, ()

    def filter(self, record: logging.LogRecord) -> bool:
        digests = record.name.startswith(_DIGEST_LOGGERS)
        self._message(record, digests)
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD:
                setattr(record, key, _clean(value, digests))
        if record.exc_info and not record.exc_text:
            # The handler would render this later from the live exception, message and all.
            record.exc_text = redact(
                "".join(traceback.format_exception(*record.exc_info)).rstrip(), digests=digests
            )
        elif record.exc_text:
            record.exc_text = redact(record.exc_text, digests=digests)
        if record.stack_info:
            record.stack_info = redact(record.stack_info, digests=digests)
        return True


def _handlers() -> list[logging.Handler]:
    """Every handler attached to the root logger or to any logger that exists now."""
    loggers = [
        logging.getLogger(),
        *(v for v in logging.root.manager.loggerDict.values() if isinstance(v, logging.Logger)),
    ]
    seen: dict[int, logging.Handler] = {}
    for target in loggers:
        for handler in target.handlers:
            seen[id(handler)] = handler
    return list(seen.values())


def install() -> None:
    """Attach one :class:`Filter` to each of :data:`LOGGERS` **and to every handler that exists**
    (idempotent).

    A logger's filter sees only records created on that exact logger, so ``uvicorn.asgi``,
    gunicorn's loggers and any child logger would slip past it; a handler's filter sees every
    record that reaches the handler, whichever logger made it. Handlers an operator adds after
    startup are covered the next time this runs (it is cheap), not before; a reverse proxy or
    CDN logs paths on its own and must redact ``/feed/`` itself."""
    for name in LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, Filter) for f in target.filters):
            target.addFilter(Filter())
    for handler in _handlers():
        if not any(isinstance(f, Filter) for f in handler.filters):
            handler.addFilter(Filter())
