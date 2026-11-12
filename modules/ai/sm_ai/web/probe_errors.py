"""What a failed probe (``POST /api/ai/test``, ``/api/ai/models``) answers (#347).

The answer is a stable ``code`` and a fixed English message for it, never the
exception's own text: an SDK's message says a good deal about whatever
answered at the base URL (a banner, an internal host name, a policy page), and
the probe routes are the only place this module reports what a provider said.
The console translates by ``code``. The exception text is logged server-side
only; the SDKs' messages carry no request headers, so the key is not in it.

The exception is classified by walking its chain (``__cause__``, then
``__context__``): pydantic-ai wraps the SDK's error, which wraps httpx's, which
wraps the socket's, and the useful part is usually at the bottom.
"""

from __future__ import annotations

import errno
import functools
import logging
import socket
from collections.abc import Iterator
from typing import Final, NamedTuple

from sm_ai.contracts.errors import (
    AiBaseUrlRefusedError,
    AiError,
    AiKeyUnreadableError,
    AiNotConfiguredError,
)
from sm_ai.core import constants
from sm_ai.core.url_safety import UnsafeURLError

__all__ = ["CODES", "Classified", "classify", "probe_error"]

logger = logging.getLogger(__name__)

BASE_URL_REFUSED: Final = "base_url_refused"
NOT_CONFIGURED: Final = "not_configured"
KEY_UNREADABLE: Final = "key_unreadable"
UNREACHABLE: Final = "unreachable"
CONNECTION_REFUSED: Final = "connection_refused"
TIMEOUT: Final = "timeout"
UNAUTHORISED: Final = "unauthorised"
HTTP_ERROR: Final = "http_error"
OTHER: Final = "other"

MESSAGES: Final = {
    BASE_URL_REFUSED: (
        "The base URL points at a private or local address, or is not an http(s) URL. "
        "To use a local endpoint, turn on 'Allow private base URLs' "
        "(allow_private_base_url)."
    ),
    NOT_CONFIGURED: "This slot is not fully configured: check the provider, model and key.",
    KEY_UNREADABLE: (
        "The stored API key cannot be decrypted with the current secret key. "
        "Re-enter it, or restore the previous key (SM_SECRET_KEY_PREVIOUS)."
    ),
    UNREACHABLE: "The endpoint could not be reached: check the base URL and the host name.",
    CONNECTION_REFUSED: "The endpoint refused the connection: is the server running?",
    TIMEOUT: f"The endpoint did not answer within {constants.TEST_TIMEOUT_SECONDS} seconds.",
    UNAUTHORISED: "The endpoint refused the API key (HTTP 401 or 403).",
    HTTP_ERROR: "The endpoint answered with an error status.",
    OTHER: "The call failed. The server log has the details.",
}
CODES: Final = tuple(MESSAGES)

_MAX_CHAIN = 12


class Classified(NamedTuple):
    """A failure class; ``status`` is the HTTP status for ``unauthorised`` and
    ``http_error``, else 0."""

    code: str
    status: int = 0


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(seen) < _MAX_CHAIN:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status(exc: BaseException) -> int:
    """The HTTP status an SDK or pydantic-ai error carries, or 0."""
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 400 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) and 400 <= value <= 599 else 0


def classify(exc: BaseException) -> Classified:
    """The failure class of a probe's exception."""
    chain = list(_chain(exc))
    for item in chain:
        if isinstance(item, AiBaseUrlRefusedError):
            return Classified(BASE_URL_REFUSED)
        if isinstance(item, UnsafeURLError):
            return Classified(UNREACHABLE if item.code == "unresolvable_host" else BASE_URL_REFUSED)
        if isinstance(item, AiKeyUnreadableError):
            return Classified(KEY_UNREADABLE)
        if isinstance(item, AiNotConfiguredError):
            return Classified(NOT_CONFIGURED)
    for item in chain:
        status = _status(item)
        if status:
            return Classified(UNAUTHORISED if status in (401, 403) else HTTP_ERROR, status)
    if any(isinstance(item, _timeouts()) for item in chain):
        return Classified(TIMEOUT)
    for item in chain:
        if isinstance(item, ConnectionRefusedError) or (
            isinstance(item, OSError) and item.errno == errno.ECONNREFUSED
        ):
            return Classified(CONNECTION_REFUSED)
    if any(isinstance(item, socket.gaierror) for item in chain):
        return Classified(UNREACHABLE)
    if any(isinstance(item, _connection_errors()) for item in chain):
        return Classified(UNREACHABLE)
    return Classified(OTHER)


def probe_error(what: str, slot: str, exc: BaseException) -> tuple[str, str, int]:
    """``(code, message, status)`` for a failed probe, logged on the way.

    A timeout is our own deadline, not the provider's failure, so it is not
    logged at all.
    """
    if isinstance(exc, TimeoutError):
        return TIMEOUT, MESSAGES[TIMEOUT], 0
    found = classify(exc)
    _log(what, slot, exc, found.code)
    return found.code, MESSAGES[found.code], found.status


def _log(what: str, slot: str, exc: BaseException, code: str) -> None:
    """One line for an expected failure, a traceback for anything else.

    An unreachable server, a refused key or a provider's error status is a
    configuration problem the card already names; its stack frames are noise.
    Anything else may be a real defect - a pydantic-ai or SDK API change - and
    keeps the traceback, without which it would read like a config problem.
    """
    if code != OTHER or isinstance(exc, (AiError, *_provider_errors())):
        logger.warning("AI %s %s failed (%s): %s", slot, what, code, exc)
    else:
        logger.warning("AI %s %s failed (%s)", slot, what, code, exc_info=exc)


@functools.cache
def _timeouts() -> tuple[type[BaseException], ...]:
    import httpx
    import httpx2
    from anthropic import APITimeoutError as AnthropicTimeout
    from openai import APITimeoutError as OpenAITimeout

    return (
        TimeoutError,
        httpx.TimeoutException,
        httpx2.TimeoutException,
        OpenAITimeout,
        AnthropicTimeout,
    )


@functools.cache
def _connection_errors() -> tuple[type[BaseException], ...]:
    import httpx
    import httpx2
    from anthropic import APIConnectionError as AnthropicConnection
    from openai import APIConnectionError as OpenAIConnection

    return (
        httpx.TransportError,
        httpx2.TransportError,
        OpenAIConnection,
        AnthropicConnection,
        ConnectionError,
    )


@functools.cache
def _provider_errors() -> tuple[type[BaseException], ...]:
    """Exception types that mean "the provider said no", imported lazily."""
    import httpx
    import httpx2
    from anthropic import APIError as AnthropicError
    from google.genai.errors import APIError as GoogleError
    from openai import APIError as OpenAIError

    # ModelAPIError, not just ModelHTTPError: pydantic-ai wraps a refused
    # connection in the former, and that is the commonest failure of all.
    from pydantic_ai.exceptions import ModelAPIError

    return (
        httpx.HTTPError,
        httpx2.HTTPError,
        OpenAIError,
        AnthropicError,
        GoogleError,
        ModelAPIError,
    )
