"""A withheld image fails exactly like an absent one, on the real host stack.

``modules/images/tests`` run on a bare FastAPI app, so the framework's
``HTTPException`` handler, the Inertia middleware and the real error template
are not exercised there. This boots ``main:app`` (``create_app``) with a real
sign-in: a view-only user reads a public collection whose images are all
withheld (``protect_originals`` with no display mutator), and each route is
compared for the *same URL* while the image or group exists and after it is
deleted, from identical copies of one signed-in session, with a fixed
``X-Correlation-ID``: raw body bytes, every header (Content-Length included)
and the decoded cookies must be equal. Only Date and Server-Timing are ignored.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from shape_compare import session_payload
from shape_compare import shape as _shape

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))
import records_collections  # noqa: E402, F401

ADMIN = ("admin@example.test", "Admin-pass-12345!")
VIEWER = ("viewer@example.test", "Viewer-pass-12345!")
# Sent on every request and echoed back: the one per-request value in an error page
# (its ``props.correlation_id``) is then fixed, so bodies compare byte for byte.
CID = "c0ffee00c0ffee00c0ffee00c0ffee00"
NEGOTIATIONS = {
    "plain": {},
    "html": {"Accept": "text/html"},
    "inertia": {"X-Inertia": "true", "X-Inertia-Version": "x"},
}


@pytest.fixture
def host(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env={**__import__("os").environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_EMAIL", ADMIN[0])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_PASSWORD", ADMIN[1])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_USER_EMAIL", VIEWER[0])
    monkeypatch.setenv("SM_USERS_BOOTSTRAP_USER_PASSWORD", VIEWER[1])
    monkeypatch.setenv("SM_RATE_LIMIT_PUBLIC", "100000/minute")
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


async def _seed(app):
    from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
    from sm_images.models import Collection, Group, Image, Visibility
    from sqlalchemy import select
    from users.models import User

    factory = app.state.sm.db.session_factory
    with tenant_scope(DEFAULT_TENANT):
        async with factory() as s:
            admin = (await s.execute(select(User).where(User.email == ADMIN[0]))).scalar_one()
            viewer = (await s.execute(select(User).where(User.email == VIEWER[0]))).scalar_one()
            coll = Collection(
                slug=f"c-{uuid.uuid4().hex[:6]}",
                name="c",
                owner_id=str(admin.id),
                visibility=Visibility.PUBLIC,
                protect_originals=True,  # no display mutator: every image is withheld
            )
            s.add(coll)
            await s.flush()
            group = Group(collection_id=coll.id, key="sensitive-site-123")
            s.add(group)
            await s.flush()
            img = Image(
                collection_id=coll.id,
                storage_key="k/x.jpg",
                filename="x.jpg",
                content_type="image/jpeg",
                size_bytes=1,
                group_id=group.id,
            )
            s.add(img)
            await s.commit()
            from permissions.models import UserPermission

            s.add(UserPermission(user_id=viewer.id, permission_key="images.view"))
            await s.commit()
            return {"slug": coll.slug, "cid": coll.id, "iid": img.id, "gid": group.id}


async def _delete(app, ids, what):
    """Make the id absent: delete the image or the group for real."""
    from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
    from sm_images.models import Group, Image
    from sqlalchemy import delete, update

    with tenant_scope(DEFAULT_TENANT):
        async with app.state.sm.db.session_factory() as s:
            if what == "image":
                await s.execute(delete(Image).where(Image.id == ids["iid"]))
            else:
                await s.execute(update(Image).values(group_id=None))
                await s.execute(delete(Group).where(Group.id == ids["gid"]))
            await s.commit()


ROUTES = [
    ("get", "/api/images/images/{i}/original"),
    ("head", "/api/images/images/{i}/original"),
    ("get", "/api/images/images/{i}/display"),
    ("get", "/api/images/images/{i}/r/small"),
    ("get", "/api/images/images/{i}"),
    ("head", "/api/images/images/{i}"),
    ("get", "/admin/images/images/{i}"),
    ("get", "/api/images/groups/{g}"),
    ("head", "/api/images/groups/{g}"),
    ("get", "/api/images/public/c/{s}/images/{i}/original"),
    ("head", "/api/images/public/c/{s}/images/{i}/original"),
    ("get", "/api/images/public/c/{s}/images/{i}/display"),
    ("get", "/api/images/public/c/{s}/images/{i}/r/small"),
    # Writes: the viewer may view the collection but not edit it. A withheld
    # target must be the absent 404 before the 403 refusal of the action (S3).
    ("patch", "/api/images/images/{i}"),
    ("delete", "/api/images/images/{i}"),
    ("post", "/api/images/images/{i}/reprocess"),
    ("patch", "/api/images/groups/{g}"),
    ("delete", "/api/images/groups/{g}"),
]
BODIES = {
    ("patch", "/api/images/images/{i}"): {"lat": 1.0, "lng": 2.0},
    ("post", "/api/images/images/{i}/reprocess"): {},
    ("patch", "/api/images/groups/{g}"): {"name": "renamed"},
}


def _expect_shape(negotiation: str, response: httpx.Response, method: str, url: str):
    if method == "head" and "/original" not in url:
        return  # a GET-only detail route: HEAD is whatever the router says, compared below
    assert response.status_code == 404, (response.status_code, response.text[:300])
    if method == "head":
        return
    api_json = "/api/" in url and ("/public/" in url or negotiation == "plain")
    if api_json:
        assert response.headers["content-type"].startswith("application/json")
    elif negotiation == "inertia":
        assert response.headers.get("x-inertia") == "true"
        assert "Error" in json.loads(response.text)["component"]
    elif negotiation == "html":
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text.lower()
    elif url.startswith("/admin/"):
        assert "text/html" in response.headers["content-type"]
    else:
        assert response.headers["content-type"].startswith("application/json")


def _negotiate(app, negotiation: str) -> dict[str, str]:
    extra = dict(NEGOTIATIONS[negotiation])
    if "X-Inertia-Version" in extra:  # the live asset version, or the host answers 409
        extra["X-Inertia-Version"] = str(app.state.sm.inertia_config.version)
    return extra


async def _sign_in(app, ids) -> httpx.Cookies:
    """Sign the viewer in once and return the cookie jar. The session carries a
    CSRF token that is embedded in every page, so both states must start
    from this one session: each gets a fresh client holding an identical copy."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        signed = await http.post(
            "/api/users/auth/login", data={"username": VIEWER[0], "password": VIEWER[1]}
        )
        assert signed.status_code in (200, 204), signed.text
        # Positive control: the viewer does see the collection, so a 404 later is the gate.
        seen = await http.get(f"/api/images/collections/{ids['cid']}")
        assert seen.status_code == 200, seen.text
        # Render one console page: the session mints its CSRF token on the first
        # render, so the snapshot must already hold it.
        page = await http.get(f"/admin/images/{ids['cid']}", headers={"Accept": "text/html"})
        assert page.status_code == 200, page.text[:300]
        return httpx.Cookies(http.cookies)


def _csrf(app, jar) -> dict[str, str]:
    """The session's CSRF token (minted by the console render in ``_sign_in``),
    read from the signed cookie, so a write reaches the resource check."""
    from simple_module_hosting.csrf import _SESSION_KEY, CSRF_HEADER

    payload = session_payload(jar["session"], app.state.sm.settings.secret_key)
    return {CSRF_HEADER: payload[_SESSION_KEY]}


async def _answers(app, jar, negotiation, method, url, body=None):
    """A fresh client from the jar snapshot, then the same request twice: the
    FIRST answer and the steady-state one are both returned."""
    transport = httpx.ASGITransport(app=app)
    extra = {**_negotiate(app, negotiation), "X-Correlation-ID": CID}
    if method not in ("get", "head"):
        extra.update(_csrf(app, jar))
    cookies = httpx.Cookies(jar) if "/public/" not in url else None
    kwargs = {} if body is None else {"json": body}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as http:
        first = await http.request(method.upper(), url, headers=extra, **kwargs)
        second = await http.request(method.upper(), url, headers=extra, **kwargs)
    return first, second


async def _run(app, negotiation, method, route, what):
    ids = await _seed(app)
    secret = app.state.sm.settings.secret_key
    url = route.format(i=ids["iid"], g=ids["gid"], s=ids["slug"])
    jar = await _sign_in(app, ids)
    body = BODIES.get((method, route))
    withheld = await _answers(app, jar, negotiation, method, url, body)
    await _delete(app, ids, what)
    absent = await _answers(app, jar, negotiation, method, url, body)
    for w, a in zip(withheld, absent, strict=True):
        _expect_shape(negotiation, w, method, url)
        _expect_shape(negotiation, a, method, url)
        assert _shape(w, secret) == _shape(a, secret)


@pytest.mark.parametrize("negotiation", sorted(NEGOTIATIONS))
@pytest.mark.parametrize(("method", "route"), ROUTES)
def test_withheld_and_absent_look_the_same(host, method, route, negotiation):
    what = "group" if "/groups/" in route else "image"

    async def go():
        async with host.router.lifespan_context(host):
            await _run(host, negotiation, method, route, what)

    asyncio.run(go())
