"""Keep fetched URLs' credentials out of the logs.

httpx logs every request at INFO (``HTTP Request: GET <url> "HTTP/1.1 200 OK"``)
with the full URL. An import's ``source_url`` (and each redirect target) is
often a presigned link whose query string *is* the credential
(``X-Amz-Signature``, ``sig=``), and a URL may carry ``user:password@``. The
:class:`Filter` installed on the ``httpx`` logger rewrites every record so a
URL keeps its scheme, host, port and path, and loses its userinfo, query and
fragment.

:func:`install` is idempotent and runs from ``ImagesModule.on_startup`` and
from :func:`sm_images.pipeline.worker_runtime.worker_runtime`, so the web
process and every worker are covered.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

import httpx

__all__ = ["Filter", "install", "redact_url"]

LOGGERS: Final = ("httpx",)

_URL: Final = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+")


def redact_url(url: Any) -> str:
    """*url* with only its scheme, host, port and path."""
    try:
        parsed = httpx.URL(str(url))
    except Exception:  # noqa: BLE001 - never let logging fail on a strange value
        return "<url>"
    return str(parsed.copy_with(username=None, password=None, query=None, fragment=None))


def _redact_text(text: str) -> str:
    return _URL.sub(lambda m: redact_url(m.group(0)), text)


def _redact_arg(arg: Any) -> Any:
    if isinstance(arg, httpx.URL):
        return redact_url(arg)
    if isinstance(arg, str) and "://" in arg:
        return _redact_text(arg)
    return arg


class Filter(logging.Filter):
    """Strips userinfo and query strings from every URL in a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "://" in record.msg:
            record.msg = _redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        return True


def install() -> None:
    """Attach one :class:`Filter` to each of :data:`LOGGERS` (idempotent)."""
    for name in LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, Filter) for f in target.filters):
            target.addFilter(Filter())
