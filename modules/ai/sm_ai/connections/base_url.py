"""Where a slot's base URL may point, checked on save and at every call (#347).

A base URL receives the slot's stored API key, so by default it must be an
http(s) URL whose host resolves only to public addresses. ``allow_private_base_url``
(off by default, changed only by a holder of ``settings.edit``) lifts the
address rule for a local endpoint such as Ollama or an in-network gateway;
the scheme rule always holds.

Three places apply it:

* **save** - :func:`save_errors`, from ``PUT /api/ai/settings``: the host is
  resolved (off the event loop) and a refused URL is a 422 that names the
  setting to turn on;
* **client build** - :func:`http_client_for`, from ``resolve`` and
  ``discovery``: synchronous and called from async code, so it never touches
  DNS. It checks the scheme and refuses an IP literal that is not public, and
  hands back the loop's shared pinned client (:mod:`sm_ai.connections.clients`);
* **connect** - that client's transport resolves and validates the host again
  for every request and dials only the validated address.

With ``allow_private_base_url`` on, only the scheme is checked and the slot
gets the shared ``private`` client: no redirects followed (the key's header
must not follow one to another host), environment proxies kept.

A slot with no base URL uses the provider's own endpoint and is not checked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sm_ai.connections.clients import client_for
from sm_ai.connections.pinned import resolve_bounded
from sm_ai.contracts.errors import AiBaseUrlRefusedError
from sm_ai.core import constants
from sm_ai.core.url_safety import (
    UnsafeURLError,
    check_url,
    is_public_address,
    literal_address,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    import httpx2

    from sm_ai.core.settings import AiSettings

__all__ = ["http_client_for", "save_errors"]


def http_client_for(
    settings: AiSettings, slot: str, base_url: str, *, shared: bool = True
) -> httpx2.AsyncClient | None:
    """The HTTP client a slot's SDK client must use, or ``None`` for the SDK's own
    (no base URL). ``shared=False`` returns one the caller closes (discovery).

    Raises :class:`AiBaseUrlRefusedError` for a URL that can be refused
    without resolving it.
    """
    if not base_url:
        return None
    field = f"{slot}_base_url"
    try:
        host, _ = check_url(base_url)
    except UnsafeURLError as error:
        raise AiBaseUrlRefusedError(field, error.code) from error
    if settings.allow_private_base_url:
        return client_for("private", base_url, shared=shared)
    literal = literal_address(host)
    if literal is not None and not is_public_address(literal):
        raise AiBaseUrlRefusedError(field, "non_public_address")
    return client_for("pinned", base_url, shared=shared)


async def _refusal(url: str, allow_private: bool) -> str | None:
    """Why ``url`` cannot be saved, or ``None``."""
    try:
        check_url(url)
        if not allow_private:
            await resolve_bounded(url)
    except UnsafeURLError as error:
        return error.code
    return None


_SAVE_MESSAGES = {
    "unresolvable_host": "the host of this URL could not be resolved",
    "non_public_address": (
        "this URL points at a private or local address; to use a local endpoint "
        "such as Ollama or an in-network gateway, turn on 'Allow private base URLs' "
        "(allow_private_base_url) first"
    ),
}


async def save_errors(
    merged: dict[str, Any], changed: Collection[str] | None = None
) -> list[dict[str, Any]]:
    """422 items for the base URLs of ``merged`` (stored settings plus the update).

    ``changed`` names the fields the update writes: a URL is checked only when it
    or ``allow_private_base_url`` is among them, so a save that touches neither
    (a new model name, a rotated key) is not refused, and made to resolve DNS,
    over a stored URL it did not change; connect time still guards that one.
    ``None`` checks every slot.

    Shaped like FastAPI's own validation items, as ``AiService.slot_errors`` is.
    """
    allow = bool(merged.get("allow_private_base_url"))
    errors: list[dict[str, Any]] = []
    for slot in constants.TEST_SLOTS:
        field = f"{slot}_base_url"
        if changed is not None and not {field, "allow_private_base_url"} & set(changed):
            continue
        url = str(merged.get(field) or "").strip()
        if not url:
            continue
        reason = await _refusal(url, allow)
        if reason is None:
            continue
        errors.append(
            {
                "type": "value_error",
                "loc": ["body", field],
                "msg": _SAVE_MESSAGES.get(reason, f"not a usable http(s) URL ({reason})"),
                "input": url,
                "ctx": {"reason": reason},
            }
        )
    return errors
