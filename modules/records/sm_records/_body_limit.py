"""Refusing an oversized write body before it is read, not after.

``max_payload_bytes`` is checked on the *serialized payload*, which means
FastAPI has already read the whole request and ``json.loads``-ed it by the
time the module can object: a 64 MiB body was read, decoded and validated in
order to produce a 422 about a 256 KiB limit. The import route has always done
this properly (``endpoints/api/_io_upload``), and this is that rule applied to
every other write under ``/api/records/*``.

**Middleware rather than a router dependency**, because a dependency runs
after the body has been parsed for the endpoint's model — which is the cost.
Middleware is the last place this module owns that sits outside the read.

**Two checks, because a request can lie in two ways.** ``Content-Length`` is
refused before a byte is read and before the handler is entered at all; a
request that declares no length — every chunked upload — is counted while it
is read and refused at the first byte past the ceiling. The second is an
``HTTPException`` and deliberately *not* this module's own ``PayloadTooLarge``:
it is raised while FastAPI reads the body for the endpoint's model, and
FastAPI wraps anything other than an ``HTTPException`` raised there in
``400 There was an error parsing the body``. Nothing has been written at that
point, so there is no rollback for ``RecordsErrorRoute`` to do either.

The framework offers no shared body-size guard to hook into (there is no
``content-length`` handling anywhere in ``simple_module_hosting``), so this is
the module's own. It is installed from
:meth:`~sm_records.module.RecordsModule.register_middleware`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Final

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sm_records import constants
from sm_records.settings import RecordsSettings

__all__ = ["ENVELOPE_HEADROOM", "BodyLimitMiddleware", "body_ceiling", "counting_receive"]

ENVELOPE_HEADROOM: Final = 65_536
"""How much a write body may exceed ``max_payload_bytes`` before this refuses.

The setting bounds one record's ``data`` once serialized; the *body* carries
that plus the envelope around it (``status``, ``slug``, ``expected_version``,
``position``), plus whatever whitespace the client's serializer left in, and
``POST /types`` carries a field list that setting never described at all. A
ceiling equal to ``max_payload_bytes`` would therefore refuse bodies the route
accepts, with a status that says the wrong thing.

So this is deliberately loose. It is not the contract — the route's own 422
is, and it still says the exact number. This is the number past which the
request is not worth reading, and 64 KiB of slack is far below the megabytes
the defect was about while staying far above any real envelope."""

_WRITE_METHODS: Final = frozenset({"POST", "PUT", "PATCH"})

_IMPORT_SUFFIX: Final = "/records/import"
"""The one write with a ceiling of its own (``max_import_bytes``, 50 MB by
default). It refuses on ``Content-Length`` and then byte by byte already, and
a 320 KB ceiling here would make the documented 50 MB limit unreachable."""


def body_ceiling(settings: RecordsSettings) -> int:
    return settings.max_payload_bytes + ENVELOPE_HEADROOM


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers") or ():
        if name == b"content-length":
            raw = value.decode("latin-1").strip()
            return int(raw) if raw.isdigit() else None
    return None


def counting_receive(receive: Receive, limit: int, refuse: Callable[[], Exception]) -> Receive:
    """``receive``, raising ``refuse()`` at the first byte past ``limit``.

    A request with no ``Content-Length`` cannot be refused from its headers,
    and the running total is the one number it cannot lie about. Shared with
    the import route (``endpoints/api/_io_upload``), which passes its own
    exception: the type differs per caller for the reason the module docstring
    gives.
    """
    seen = 0

    async def counted() -> Message:
        nonlocal seen
        message = await receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body", b"") or b"")
            if seen > limit:
                raise refuse()
        return message

    return counted


async def _refuse(declared: int, limit: int, send: Send) -> None:
    body = json.dumps(
        {"detail": f"the request body is {declared} bytes, over the {limit}-byte limit"}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodyLimitMiddleware:
    """Bound every ``/api/records/*`` write body. Reads nothing else."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self._limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            # Before ``self.app``, so the route is never entered and the body
            # is never read — which is the whole point of doing this here.
            await _refuse(declared, limit, send)
            return
        too_large = f"the request body is over the {limit}-byte limit"
        guarded = counting_receive(
            receive, limit, lambda: HTTPException(status_code=413, detail=too_large)
        )
        await self.app(scope, guarded, send)

    def _limit(self, scope: Scope) -> int | None:
        """The ceiling for this request, or ``None`` to stay out of the way.

        Out of the way for: anything that is not an HTTP write, anything
        outside this module's API prefix (the view routes are reads and the
        host's other modules are not ours to bound), the import route, and an
        app whose settings are not hydrated yet — during boot there is nothing
        to read a number from, and refusing on a default would be a ceiling
        the operator never chose.
        """
        if scope["type"] != "http" or scope.get("method") not in _WRITE_METHODS:
            return None
        path = scope.get("path", "")
        if not path.startswith(constants.ROUTE_PREFIX_API) or path.endswith(_IMPORT_SUFFIX):
            return None
        app: Any = scope.get("app")
        container = getattr(getattr(app, "state", None), constants.PACKAGE, None)
        settings = getattr(container, "settings", None)
        return None if settings is None else body_ceiling(settings)
