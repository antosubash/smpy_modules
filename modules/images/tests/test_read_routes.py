"""No read route tells a stranger (or the anonymous) anything about a private collection.

Parametrised over :data:`tests.read_routes.READ_ROUTES`, which every task that
adds a ``GET`` extends. The shape of the failure it guards against: a list or a
count that forgot the access policy, a sub-resource route that checked the
image but not its collection, a 403 where a 404 hides existence.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sm_images import constants
from sm_images.models import Group, ImportJob, Prompt, RegroupJob, Rendition, Visibility
from sm_images.storage import ImageStore

from tests import read_routes
from tests.access_support import OWNER, collection, image
from tests.isolation_support import ACME, as_
from tests.read_routes import COLLECTION, IMAGE, JOB, LIST, PUBLIC, READ_ROUTES
from tests.stub_auth import as_user

ROUTES = pytest.mark.parametrize("route", READ_ROUTES, ids=lambda r: f"{r.method} {r.path}")
LIST_URL = "/api/images/collections"
SIZE = "small"
STRANGER = as_user("sam", ("images.view", "images.create"))


@pytest_asyncio.fixture
async def secret(client, storage):
    """olga's private collection and an image in it (stored, with a ``small``
    rendition, so the byte routes have something to serve its owner), plus one
    public collection."""
    private = collection("secret-trees", Visibility.PRIVATE, OWNER)
    public = collection("open-trees", Visibility.PUBLIC, OWNER)
    async with client.db_state.session_factory() as s:
        s.add_all([private, public])
        await s.flush()
        pic = image(private, "secret-photo.jpg")
        s.add(pic)
        await s.flush()
        site = Group(collection_id=private.id, key="secret-site")
        s.add(site)
        await s.flush()
        pic.group_id = site.id
        regroup_job = RegroupJob(collection_id=private.id, pattern="(?P<group>secret-pattern)")
        s.add(regroup_job)
        s.add(Rendition(image_id=pic.id, size=SIZE, storage_key="k/small", width=1, height=1))
        job = ImportJob(collection_id=private.id, mapping={"url_prop": "url"})
        s.add(job)
        prompt = Prompt(collection_id=private.id, name="secret-prompt", instruction="secret-ask")
        s.add(prompt)
        await s.commit()
    store = ImageStore(storage)
    for key in (pic.storage_key, "k/small"):
        await store.put(key, b"secret-bytes", content_type="image/jpeg", size=12)
    return {
        "collection_id": str(private.id),
        "image_id": str(pic.id),
        "job_id": str(job.id),
        "group_id": str(site.id),
        "regroup_id": str(regroup_job.id),
        "prompt_id": str(prompt.id),
        "slug": private.slug,
        "public_slug": public.slug,
        "size": SIZE,
    }


def fill(route, ids) -> str:
    return route.path.format(**ids)


def absent(route, ids) -> str:
    """The same route for ids that do not exist at all."""
    return route.path.format(
        collection_id=uuid.uuid4(),
        image_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        regroup_id=uuid.uuid4(),
        prompt_id=uuid.uuid4(),
        slug="no-such-collection",
        size=SIZE,
    )


def leaks(text: str, ids) -> list[str]:
    return [
        what
        for what in (
            ids["collection_id"],
            ids["image_id"],
            ids["job_id"],
            ids["group_id"],
            ids["regroup_id"],
            ids["prompt_id"],
            "secret-prompt",
            "secret-ask",
            "secret-pattern",
            "secret-site",
            ids["slug"],
            "secret-photo.jpg",
            "secret-bytes",
        )
        if what in text
    ]


@ROUTES
async def test_every_read_route_hides_private_collection(client, secret, route):
    sent = {"method": route.method}
    url = fill(route, secret)

    if route.needs in (COLLECTION, IMAGE, JOB):
        got = await client.request(url=url, headers=STRANGER, **sent)
        assert got.status_code == 404, got.text
        assert leaks(got.text, secret) == []
        # no oracle: indistinguishable from an id that never existed
        nothing = await client.request(url=absent(route, secret), headers=STRANGER, **sent)
        assert (nothing.status_code, nothing.json()) == (got.status_code, got.json())
        # the admin surface refuses the anonymous before it looks anything up
        anon = await client.request(url=url, **sent)
        assert anon.status_code == 401
        assert leaks(anon.text, secret) == []
    elif route.needs == LIST:
        got = await client.request(url=url, headers=STRANGER, **sent)
        assert got.status_code == 200, got.text
        assert leaks(got.text, secret) == []
        assert secret["public_slug"] in got.text  # not vacuous: the list has rows
        anon = await client.request(url=url, **sent)
        assert anon.status_code == 401
    elif route.needs == PUBLIC:
        for headers in ({}, STRANGER):
            got = await client.request(url=url, headers=headers, **sent)
            assert got.status_code == 404, got.text
            assert leaks(got.text, secret) == []
    else:  # pragma: no cover - a typo in read_routes.py
        pytest.fail(f"unknown needs {route.needs!r}")


@ROUTES
async def test_the_owner_can_still_read_what_the_stranger_cannot(client, secret, route):
    """The other half: the 404 above is the policy, not a broken route."""
    if route.needs == PUBLIC:
        pytest.skip("anonymous surface: private is private for its owner too")
    from tests.test_share_candidates import FakeDirectory, person

    client.app.state.user_directory = FakeDirectory([person("vic")])
    owner = as_user("olga", ("images.view", "images.create"))
    got = await client.request(route.method, fill(route, secret), headers=owner)
    assert got.status_code == 200, got.text
    if route.needs == LIST:
        assert secret["slug"] in got.text


def test_every_get_route_is_listed(client):
    """A new ``GET`` without a ``READ_ROUTES`` entry is a route nobody tried to leak through."""
    listed = {(r.method, r.path.split("?")[0]) for r in READ_ROUTES}
    # Through the OpenAPI document: FastAPI nests included routers, so
    # ``app.routes`` no longer lists them flat. (A route hidden from the schema
    # with ``include_in_schema=False`` must be added to READ_ROUTES by hand.)
    served = {
        ("GET", path)
        for path, item in client.app.openapi()["paths"].items()
        if "get" in item and path.startswith((constants.ROUTE_PREFIX_API, constants.PUBLIC_PREFIX))
    }
    missing = sorted(
        f"{m} {p}" for m, p in served - listed if f"{m} {p}" not in read_routes.NOT_A_LEAK_SURFACE
    )
    assert missing == [], f"add these to tests/read_routes.py: {missing}"
    stale = sorted(f"{m} {p}" for m, p in listed - served)
    assert stale == [], f"in read_routes.py but not served: {stale}"


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_unbound_tenant_admin_403(two_tenants, method):
    """A signed-in request on a multi-tenant host that resolved no tenant is refused."""
    client = two_tenants
    nobody = as_(None, "olga", ("images.view", "images.create"))
    body = {"name": "x"} if method == "POST" else None
    got = await client.request(method, LIST_URL, headers=nobody, json=body)
    assert got.status_code == 403
    assert got.json()["code"] == constants.TENANT_REQUIRED_CODE


@pytest.mark.unbound_tenant
async def test_a_list_is_scoped_to_the_callers_tenant(two_tenants):
    client = two_tenants
    mine = as_(ACME, "olga", ("images.view", "images.create"))
    other = as_("globex", "olga", ("images.view", "images.create", "images.manage"))
    made = await client.post("/api/images/collections", json={"name": "Acme only"}, headers=mine)
    assert made.status_code == 201, made.text
    got = await client.get("/api/images/collections", headers=other)
    assert got.json()["items"] == []
    assert (
        await client.get(f"/api/images/collections/{made.json()['id']}", headers=other)
    ).status_code == 404
