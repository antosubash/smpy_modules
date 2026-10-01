"""``POST /billing/webhooks/stripe`` — public; the signature is the authentication.

Mounted on the view router (prefix ``/billing``) with no CSRF dependency, and
exempted from ``AuthMiddleware`` in ``BillingModule.register_public_routes``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sm_billing import constants as c
from sm_billing.webhooks import process_webhook

router = APIRouter()


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request) -> JSONResponse:
    services = getattr(request.app.state, c.PACKAGE)
    provider = services.provider
    if provider is None or provider.name != c.PROVIDER_STRIPE:
        return JSONResponse({"detail": "stripe_not_configured"}, status_code=404)
    status, detail = await process_webhook(
        request.app, provider, await request.body(), request.headers
    )
    return JSONResponse({"detail": detail}, status_code=status)
