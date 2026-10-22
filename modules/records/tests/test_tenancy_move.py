"""A collection move stays inside its tenant (#82).

Both tenants have a ``post`` type of their own, and a uuid (``SAME``) in
each. Moving ``globex``'s into a collection copies ``globex``'s rows and
deletes ``globex``'s rows — every Core statement of the move carries an
explicit ``tenant_id``, because the tenancy guard cannot see Core DML.
``two_tenants`` checks on the way out that no ``acme`` row changed.
"""

from __future__ import annotations

import pytest

from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections
from tests.isolation_support import ACME, API, GLOBEX, GLOBEX_REF, POST, SAME, as_

pytestmark = pytest.mark.unbound_tenant

G, A = as_(GLOBEX), as_(ACME)


async def test_moving_one_tenants_type_leaves_the_other_tenant_alone(two_tenants):
    current = (await two_tenants.get(f"{API}/{POST}", headers=G)).json()
    moved = await two_tenants.put(
        f"{API}/{POST}",
        json={"expected_version": current["version"], "collection": "events"},
        headers=G,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["collection"] == "events"

    mine = await two_tenants.get(f"{API}/{POST}/records/{SAME}", headers=G)
    assert mine.status_code == 200
    assert mine.json()["data"]["title"] == "globex same"
    ref = await two_tenants.get(f"{API}/{POST}/records/{GLOBEX_REF}?expand=link", headers=G)
    assert ref.json()["expanded"]["link"][0]["display_title"] == "globex same"

    theirs = await two_tenants.get(f"{API}/{POST}", headers=A)
    assert theirs.json()["collection"] is None
    still = await two_tenants.get(f"{API}/{POST}/records/{SAME}", headers=A)
    assert still.status_code == 200
    assert still.json()["data"]["title"] == "acme same"
