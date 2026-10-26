"""``pagebuilder.contracts.public`` — the site 404 news' reader pages render (#248).

The rendering itself is ``test_public_not_found.py``'s; news' own suite drives
the contract end to end. This pins what the contract adds: it answers ``None``
where pagebuilder is not mounted, it reads the frame with the caller's tenant
bound — or with no database at all when there is none — and it refuses a
tenant that contradicts the one the request resolved.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pagebuilder.contracts import public
from pagebuilder.settings import PagebuilderSettings
from simple_module_db import current_tenant_id

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


def _request(services: Any, resolved: str | None = None) -> Any:
    state = SimpleNamespace() if services is None else SimpleNamespace(pagebuilder=services)
    return SimpleNamespace(
        app=SimpleNamespace(state=state), state=SimpleNamespace(tenant_id=resolved)
    )


async def test_not_mounted_is_none() -> None:
    db: Any = object()
    for services in (None, SimpleNamespace(), SimpleNamespace(settings=None)):
        answer = await public.render_not_found(
            _request(services), None, db, locale="en", tenant_id="acme"
        )
        assert answer is None


@pytest.mark.parametrize("tenant", ["acme", None])
async def test_the_frame_is_read_in_the_callers_tenant(monkeypatch, tenant) -> None:
    seen: dict[str, Any] = {}

    async def fake(request, inertia, settings, *, locale, db, detail):
        seen.update(tenant=current_tenant_id.get(), db=db, locale=locale, detail=detail)
        return "rendered"

    monkeypatch.setattr(public, "_render", fake)
    db: Any = object()
    services = SimpleNamespace(settings=PagebuilderSettings())
    answer = await public.render_not_found(
        _request(services), None, db, locale="de", tenant_id=tenant, detail="Article not found"
    )
    assert answer == "rendered"
    assert seen["locale"] == "de" and seen["detail"] == "Article not found"
    if tenant is None:
        # No tenant: no database handed on, so no other site's layout is read.
        assert seen["db"] is None
    else:
        assert seen["tenant"] == tenant and seen["db"] is db


@pytest.mark.parametrize("mounted", [True, False])
async def test_a_tenant_other_than_the_resolved_one_is_refused(monkeypatch, mounted) -> None:
    async def fake(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("rendered another tenant's frame")

    monkeypatch.setattr(public, "_render", fake)
    services = SimpleNamespace(settings=PagebuilderSettings()) if mounted else None
    db: Any = object()
    with pytest.raises(public.TenantMismatchError, match="globex"):
        await public.render_not_found(
            _request(services, resolved="acme"), None, db, locale="en", tenant_id="globex"
        )


@pytest.mark.parametrize(
    ("resolved", "tenant"),
    # Its own tenant; nothing resolved (a single-tenant host); no tenant at all,
    # which renders no layout; a malformed state value, which resolves nothing.
    [("acme", "acme"), (None, "default"), ("acme", None), ("", "default")],
)
async def test_the_resolved_tenant_or_none_is_accepted(monkeypatch, resolved, tenant) -> None:
    async def fake(*args, **kwargs):
        return "rendered"

    monkeypatch.setattr(public, "_render", fake)
    services = SimpleNamespace(settings=PagebuilderSettings())
    db: Any = object()
    answer = await public.render_not_found(
        _request(services, resolved=resolved), None, db, locale="en", tenant_id=tenant
    )
    assert answer == "rendered"
