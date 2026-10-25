"""``RequiresAiRequest`` and the meter registration without a running billing.

Billing is optional for ai (#99): without it the dependency is a no-op, the
meter is not registered, and no billing code is imported. The suite with
billing running is ``test_metering_billing.py``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from simple_module_db.deps import get_db
from sm_ai import constants, metering
from sm_ai.contracts import METER_REQUESTS, RequiresAiRequest


def _app(dependency) -> FastAPI:
    app = FastAPI()

    @app.post("/chat")
    async def chat(outcome=dependency):
        return {"outcome": outcome}

    # A metered route resolves get_db (RequiresQuota does); there is no host here.
    app.dependency_overrides[get_db] = lambda: None
    return app


async def _post(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post("/chat")


def test_the_meter_key_is_the_plan_limit_key():
    assert METER_REQUESTS == "ai.requests"


async def test_without_billing_it_is_a_no_op(monkeypatch):
    monkeypatch.setattr(metering, "billing_metering_installed", lambda: False)
    dependency = RequiresAiRequest()
    assert dependency.dependency is metering._unmetered
    response = await _post(_app(dependency))
    assert response.status_code == 200
    assert response.json() == {"outcome": None}


def test_a_host_without_billing_never_imports_it():
    # A fresh interpreter in which sm_billing cannot be imported at all.
    script = textwrap.dedent(
        """
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                if name == "sm_billing" or name.startswith("sm_billing."):
                    raise ModuleNotFoundError(name)

        sys.meta_path.insert(0, Block())
        from sm_ai import metering
        from sm_ai.contracts import RequiresAiRequest

        assert RequiresAiRequest().dependency is metering._unmetered
        assert not any(m.startswith("sm_billing") for m in sys.modules)
        print("ok")
        """
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert done.stdout.strip() == "ok", done.stderr


def test_a_billing_without_metering_counts_as_absent(monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(metering, "find_spec", missing)
    assert metering.billing_metering_installed() is False
    monkeypatch.setattr(metering, "find_spec", lambda name: None)
    assert metering.billing_metering_installed() is False


async def test_installed_but_not_running_billing_limits_nothing():
    # The workspace installs billing; an app that does not run it has no
    # app.state.billing_usage, and RequiresQuota then yields None.
    pytest.importorskip("sm_billing.metering.deps")
    dependency = RequiresAiRequest()
    assert dependency.dependency is not metering._unmetered
    response = await _post(_app(dependency))
    assert response.status_code == 200
    assert response.json() == {"outcome": None}


@pytest.mark.parametrize("qty", [0, -1, True, 1.5, 2**53 + 1])
@pytest.mark.parametrize("installed", [True, False])
def test_a_bad_quantity_is_a_bug_either_way(monkeypatch, qty, installed):
    monkeypatch.setattr(metering, "billing_metering_installed", lambda: installed)
    with pytest.raises(ValueError, match="qty"):
        RequiresAiRequest(qty)


def test_no_registry_registers_nothing():
    app = FastAPI()
    assert metering.register_meter(app) is False


def test_the_registry_gets_a_counter_with_the_ai_label():
    calls: list[dict] = []
    app = FastAPI()
    app.state.billing_meters = SimpleNamespace(define=lambda **kw: calls.append(kw))
    assert metering.register_meter(app) is True
    assert calls == [
        {
            "key": "ai.requests",
            "kind": "counter",
            "unit": "count",
            "label_key": constants.METER_REQUESTS_LABEL_KEY,
        }
    ]
