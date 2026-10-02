"""Billing errors and their JSON mapping (``{"detail": code, ...}``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
    return JSONResponse({"detail": exc.code, **exc.extra}, status_code=exc.status_code)


async def _plan_error(_: Request, exc: PlanError) -> JSONResponse:
    return JSONResponse({"detail": exc.code}, status_code=exc.status_code)


async def _provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    logger.warning("billing: provider call failed on %s: %s", request.url.path, exc)
    return JSONResponse({"detail": "provider_error", "message": str(exc)}, status_code=502)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BillingError, _billing_error)
    app.add_exception_handler(PlanError, _plan_error)
    app.add_exception_handler(ProviderError, _provider_error)
