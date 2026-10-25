"""A newsletter's confirm and unsubscribe links (#101, design §4.1, §4.4, §7.2).

``POST /api/records/submissions/confirm`` and ``…/unsubscribe``, under the
submissions prefix and its ``GET``/``POST`` exemption. The body is ``{t}``,
as JSON **or** form-encoded (a page without script, and RFC 8058's one-click
unsubscribe later). No ``Origin`` or content-type check, and no CSRF token:
the signed link *is* the capability, and a cross-site forger cannot make one.

**The tenant comes from the link** (:func:`_bind`), the one documented
exception to "the public surface binds the resolved tenant" — the mail's links
are built on ``public_base_url``, which in multi mode is the apex host, where
no tenant resolves. It is safe because the link's ``gate`` MAC covers the
tenant and is checked before any statement runs. A request whose host *did*
resolve a tenant must name the same one, or the link is treated as invalid.
The binding is the first dependency, so ``get_db``'s commit runs inside it.

Unsubscribe answers ``200 {"status": "unsubscribed"}`` whatever the link —
forged, for another tenant, for nobody, already used — so it is no oracle and
a second click sees what the first did. Confirm answers ``410 link_expired``
for every link it cannot honour. Every answer is ``no-store``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions_api import LinkResult
from sm_records.deps import get_settings, request_db
from sm_records.endpoints.api._responses import SUBMISSION_LINK, responses
from sm_records.endpoints.api.public_submissions_public import SubmissionRoute
from sm_records.public_submissions import abuse, links, opt_in
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.tokens import host_secret
from sm_records.settings import RecordsSettings
from sm_records.tenancy import _resolved, tenant_scope

__all__ = ["router"]

router = APIRouter(
    route_class=SubmissionRoute,
    responses=responses(*SUBMISSION_LINK),
    dependencies=[Depends(abuse.switch)],
)


async def _token(request: Request) -> object:
    """``t`` from a JSON or a form-encoded body; ``None`` from anything else."""
    media = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    raw = await request.body()
    if media == "application/json":
        try:
            body = json.loads(raw)
        except ValueError:
            return None
        return body.get("t") if isinstance(body, dict) else None
    if media == "application/x-www-form-urlencoded":
        values = parse_qs(raw.decode("utf-8", "replace")).get("t")
        return values[0] if values else None
    return None


def _bind(action: links.Action) -> Callable[[Request], AsyncIterator[links.Link | None]]:
    async def bind(request: Request) -> AsyncIterator[links.Link | None]:
        try:
            link = links.parse(host_secret(request.app), action, await _token(request))
        except links.LinkInvalid:
            yield None
            return
        resolved = _resolved(request)
        if resolved is not None and resolved != link.tenant:
            yield None
            return
        with tenant_scope(link.tenant):
            yield link

    return bind


_confirm_link = _bind(links.CONFIRM)
_unsubscribe_link = _bind(links.UNSUBSCRIBE)


@router.post(
    "/confirm",
    response_model=LinkResult,
    responses=responses(410),
    dependencies=[Depends(_confirm_link)],
)
async def confirm_subscription(
    request: Request,
    link: Any = Depends(_confirm_link),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> LinkResult:
    """Confirm a newsletter signup: ``confirmed``, ``already_confirmed``, or
    ``410 link_expired`` for any link that cannot be honoured."""
    if link is None:
        raise SubmissionRefused("link_expired", "this link has expired or is no longer valid")
    status = await opt_in.confirm(db, host_secret(request.app), link, settings)
    await db.flush()
    return LinkResult(status=status)  # type: ignore[arg-type]


@router.post(
    "/unsubscribe",
    response_model=LinkResult,
    dependencies=[Depends(_unsubscribe_link)],
)
async def unsubscribe(
    request: Request,
    link: Any = Depends(_unsubscribe_link),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> LinkResult:
    """Leave a newsletter list. Always ``200 {"status": "unsubscribed"}``."""
    if link is not None:
        await opt_in.unsubscribe(db, host_secret(request.app), link, settings)
        await db.flush()
    return LinkResult(status="unsubscribed")
