"""Billing errors and their JSON mapping (``{"detail": code, ...}``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sm_billing.contracts.metering import (
    HoldExpired,
    HoldNotFound,
    IdempotencyConflict,
    QuotaExceededError,
)
from sm_billing.contracts.provider import ProviderError
from sm_billing.plans import PlanError

logger = logging.getLogger(__name__)


class BillingError(Exception):
    def __init__(self, code: str, status_code: int = 400, **extra: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.extra = extra


async def _billing_error(_: Request, exc: BillingError) -> JSONResponse:
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        {"detail": exc.code, **exc.extra}, status_code=exc.status_code, headers=headers
    )


async def _plan_error(_: Request, exc: PlanError) -> JSONResponse:
    return JSONResponse({"detail": exc.code}, status_code=exc.status_code)


async def _provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    logger.warning("billing: provider call failed on %s: %s", request.url.path, exc)
    return JSONResponse({"detail": "provider_error", "message": str(exc)}, status_code=502)


async def _idempotency_conflict(_: Request, exc: IdempotencyConflict) -> JSONResponse:
    return JSONResponse({"detail": "idempotency_conflict"}, status_code=409)


def quota_body(exc: QuotaExceededError) -> dict[str, Any]:
    """``{"detail": "quota_exceeded", meter, limit, used, requested, resets_at}``;
    ``resets_at`` is ``None`` for a gauge, which never resets."""
    outcome = exc.outcome
    resets_at = outcome.period_end.isoformat() if outcome.period_end is not None else None
    return {
        "detail": "quota_exceeded",
        "meter": exc.meter,
        "limit": outcome.limit,
        "used": outcome.used,
        "requested": outcome.requested,
        "resets_at": resets_at,
    }


async def _quota_exceeded(_: Request, exc: QuotaExceededError) -> JSONResponse:
    return JSONResponse(quota_body(exc), status_code=402)


async def _hold_not_found(_: Request, exc: HoldNotFound) -> JSONResponse:
    return JSONResponse({"detail": "hold_not_found"}, status_code=404)


async def _hold_expired(_: Request, exc: HoldExpired) -> JSONResponse:
    return JSONResponse({"detail": "hold_expired", "status": exc.status}, status_code=409)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BillingError, _billing_error)
    app.add_exception_handler(PlanError, _plan_error)
    app.add_exception_handler(ProviderError, _provider_error)
    app.add_exception_handler(IdempotencyConflict, _idempotency_conflict)
    app.add_exception_handler(QuotaExceededError, _quota_exceeded)
    app.add_exception_handler(HoldNotFound, _hold_not_found)
    app.add_exception_handler(HoldExpired, _hold_expired)
