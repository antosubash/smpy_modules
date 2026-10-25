"""Website submissions (#101): the anonymous form definition and submit.

At the fixed :data:`~sm_records.constants.PUBLIC_SUBMISSIONS_API_PREFIX`
(``/api/records/submissions/``), exempted from ``AuthMiddleware`` for ``GET``
and ``POST`` by :meth:`~sm_records.module.RecordsModule.register_public_routes`.
**No authentication dependency and no read of ``request.state.user``**, as on
the read API: these answer callers with no session.

**No ``RequiresCsrf`` either, on purpose.** The pages that host a form are
anonymous and publicly cached, so they carry no session token to check. A
submit instead needs ``Content-Type: application/json`` (which forces a CORS
preflight no policy here admits), an ``Origin`` this host accepts, and a valid
signed form token — :mod:`sm_records.public_submissions.abuse` and
``.tokens``. A same-site forger can only send spam, which the rate limits
bound.

Dependencies run in order: the tenant (``bind_public``, the shared 404 with
none), then the guard (master switch, content type, origin). Every answer is
``Cache-Control: no-store`` — a definition carries a fresh token and a
submit's answer is nobody else's.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions_api import (
    SubmissionAccepted,
    SubmissionDefinition,
    SubmitBody,
)
from sm_records.deps import get_settings, request_db
from sm_records.endpoints.api._errors import PublicErrorRoute
from sm_records.endpoints.api._responses import SUBMISSION, responses
from sm_records.public_submissions import abuse
from sm_records.public_submissions.definition import accepting_type, definition
from sm_records.public_submissions.submit import submit
from sm_records.public_submissions.tokens import host_secret
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bind_public, bound_tenant

__all__ = ["router"]


class SubmissionRoute(PublicErrorRoute):
    """The public route class, with ``no-store`` on every answer."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            response = await handler(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        return wrapped


router = APIRouter(
    route_class=SubmissionRoute,
    responses=responses(*SUBMISSION),
    dependencies=[Depends(bind_public), Depends(abuse.guard)],
)


@router.get("/{type_key}", response_model=SubmissionDefinition)
async def get_submission_form(
    type_key: str,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    locale: str | None = Query(default=None, max_length=16),
) -> SubmissionDefinition:
    """What a form renders: the type's public fields, the consent text in
    ``?locale=`` (else the default content locale's) and a signed token to
    send back. Fetched live when the form mounts. A type that is unknown,
    does not accept submissions or has them switched off is the shared 404."""
    rtype = await accepting_type(db, type_key)
    secret = host_secret(request.app)
    return definition(rtype, settings, secret=secret, tenant=bound_tenant(), locale=locale)


@router.post("/{type_key}/submit", status_code=202, response_model=SubmissionAccepted)
async def submit_form(
    type_key: str,
    body: SubmitBody,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> SubmissionAccepted:
    """Store a visitor's submission as a draft record and queue its
    notification. ``202 {"ok": true}`` — also for a honeypot hit, which is
    stored nowhere. Refusals carry a ``code``; see the reference."""
    await submit(request, db, type_key, body, settings)
    return SubmissionAccepted()
