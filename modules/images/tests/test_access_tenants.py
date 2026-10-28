"""``internal`` means "a member of *this* tenant", and that rests on the binding.

The policy adds no tenant predicate: the ``MultiTenantMixin`` filter under
``bind_admin``/``bind_public`` does. So another tenant's signed-in user, who
would pass ``visibility='internal'`` on the policy alone, must still see
nothing of acme's.
"""

from __future__ import annotations

import pytest
from simple_module_hosting.middleware import TENANT_HEADER
from sm_images.models import Visibility
from sm_images.tenancy import tenant_scope

from tests.access_support import ADMIN_BASE, PUBLIC_BASE, STRANGER, collection, headers, mount
from tests.isolation_support import ACME, GLOBEX

pytestmark = pytest.mark.unbound_tenant


async def _seed_acme(client) -> dict[str, str]:
    rows = {
        "int": collection("acme-int", Visibility.INTERNAL),
        "pub": collection("acme-pub", Visibility.PUBLIC),
    }
    with tenant_scope(ACME):
        async with client.db_state.session_factory() as s:
            s.add_all(list(rows.values()))
            await s.commit()
    return {k: str(v.id) for k, v in rows.items()}


async def test_internal_collections_do_not_cross_tenants(two_tenants):
    client = two_tenants
    mount(client.app)
    ids = await _seed_acme(client)

    member = headers(STRANGER, tenant=ACME)
    outsider = headers(STRANGER + "-g", tenant=GLOBEX)
    outsider_perms = {**outsider, "X-Test-Perms": "images.view,images.manage"}

    assert (await client.get(ADMIN_BASE, headers=member)).json() == ["acme-int", "acme-pub"]
    assert (await client.get(f"{ADMIN_BASE}/{ids['int']}", headers=member)).status_code == 200

    for caller in (outsider, outsider_perms):
        listing = await client.get(ADMIN_BASE, headers=caller)
        assert listing.status_code == 200
        assert listing.json() == []
        for coll_id in ids.values():
            response = await client.get(f"{ADMIN_BASE}/{coll_id}", headers=caller)
            assert response.status_code == 404


async def test_public_page_is_the_resolved_tenants(two_tenants):
    client = two_tenants
    mount(client.app)
    await _seed_acme(client)
    assert (
        await client.get(f"{PUBLIC_BASE}/c/acme-pub", headers={TENANT_HEADER: ACME})
    ).status_code == 200
    assert (
        await client.get(f"{PUBLIC_BASE}/c/acme-pub", headers={TENANT_HEADER: GLOBEX})
    ).status_code == 404
    # No tenant resolved on a multi-tenant host: the public surface answers 404.
    assert (await client.get(f"{PUBLIC_BASE}/c/acme-pub")).status_code == 404
