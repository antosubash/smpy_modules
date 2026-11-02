"""Shared by the StripeProvider tests: local webhook signing and a recording ``client.v1``.

The ``provider`` fixture that wires the recorder in lives in ``conftest.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import stripe

SECRET = "whsec_test"
PERIOD_END = 1793491200  # 2026-11-01T00:00:00Z

SUBSCRIPTION = {
    "id": "sub_1",
    "object": "subscription",
    "customer": "cus_1",
    "status": "trialing",
    "cancel_at_period_end": False,
    "trial_end": 1792281600,
    "metadata": {"tenant_id": "t1"},
    "items": {
        "object": "list",
        "data": [
            {
                "id": "si_1",
                "object": "subscription_item",
                "quantity": 4,
                "current_period_end": PERIOD_END,
                "price": {"id": "price_team_m", "object": "price"},
            }
        ],
    },
}


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={ts},v1={sig}"}


def _event(etype: str, obj: dict) -> dict:
    return {"id": "evt_1", "object": "event", "type": etype, "data": {"object": obj}}


class _Recorder:
    """Stands in for one ``client.v1.<resource>`` service."""

    def __init__(self, calls: list, name: str, result: dict) -> None:
        self._calls, self._name, self._result = calls, name, result

    def __getattr__(self, method: str):
        async def call(*args: Any, **kwargs: Any):
            self._calls.append((f"{self._name}.{method}", args, kwargs.get("params")))
            self.options = kwargs.get("options")
            return stripe.StripeObject.construct_from(self._result, "sk_test")

        return call
