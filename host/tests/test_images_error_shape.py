"""A withheld image fails exactly like an absent one, on the real host stack.

``modules/images/tests`` run on a bare FastAPI app, so the framework's
``HTTPException`` handler, the Inertia middleware and the real error template
are not exercised there. This boots ``main:app`` (``create_app``) with a real
sign-in: a view-only user reads a public collection whose images are all
withheld (``protect_originals`` with no display mutator), and each route is
compared for the *same URL* while the image or group exists and after it is
deleted. Only ``props.correlation_id`` and request-id/Date headers differ.
"""

from __future__ import annotations

import asyncio
import gzip
import importlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))
import records_collections  # noqa: E402, F401

ADMIN = ("admin@example.test", "Admin-pass-12345!")
VIEWER = ("viewer@example.test", "Viewer-pass-12345!")
# Per-request values only: the clock, the request/correlation ids and timings.
IGNORED = {"date", "x-request-id", "x-correlation-id", "server-timing"}
CID = "[0-9a-f]{32}"
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
    from sm_images.models import Collection, Group, Image, Visibility
    from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
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
    from sm_images.models import Group, Image
    from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
    from sqlalchemy import delete, update

    with tenant_scope(DEFAULT_TENANT):
        async with app.state.sm.db.session_factory() as s:
            if what == "image":
                await s.execute(delete(Image).where(Image.id == ids["iid"]))
            else:
                await s.execute(update(Image).values(group_id=None))
                await s.execute(delete(Group).where(Group.id == ids["gid"]))
            await s.commit()


def _cookies(response: httpx.Response) -> list[tuple[str, str]]:
    """Set-Cookie as (name, attributes): the value is a signed session blob that
    differs per request; the name and every attribute (path, max-age, samesite,
    httponly, secure) must match."""
    out = []
    for raw in response.headers.get_list("set-cookie"):
        first, _, attrs = raw.partition(";")
        out.append((first.partition("=")[0].strip(), attrs.strip()))
    return sorted(out)


def _normalise(response: httpx.Response):
    """Everything must match except the correlation id VALUE (32 hex digits, under
    exactly its JSON key or its HTML-escaped prop key) and the ignored headers."""
    body = response.text
    body = re.sub(rf'("correlation_id":\s*")({CID})(")', r"\1CID\3", body)
    body = re.sub(rf"(&quot;correlation_id&quot;:&quot;)({CID})(&quot;)", r"\1CID\3", body)
    headers = {k: v for k, v in response.headers.items() if k not in IGNORED and k != "set-cookie"}
    if "content-encoding" in headers:
        # A compressed length varies with the bytes of the (random) ids inside; the
        # decoded body is compared in full instead.
        headers.pop("content-length", None)
    return response.status_code, body, headers, _cookies(response)


def test_the_comparator_catches_what_it_must():
    """Guard the guard: a differing detail text, Content-Length, cookie attribute
    or a non-id after ``correlation_id`` must not compare equal."""

    def resp(text="{}", headers=None, status=404):
        return httpx.Response(status, text=text, headers=headers or {})

    same = '{"detail":"x","correlation_id":"%s"}'
    assert _normalise(resp(same % ("a" * 32))) == _normalise(resp(same % ("b" * 32)))
    assert _normalise(resp('{"detail":"correlation_id withheld"}')) != _normalise(
        resp('{"detail":"correlation_id absent"}')
    )
    assert _normalise(resp('{"detail":"a"}')) != _normalise(resp('{"detail":"b"}'))
    assert _normalise(resp("", {"content-length": "5"})) != _normalise(
        resp("", {"content-length": "6"})
    )
    one = resp(headers={"set-cookie": "session=abc; path=/; httponly"})
    other = resp(headers={"set-cookie": "session=xyz; path=/; httponly"})
    assert _normalise(one) == _normalise(other)
    assert _normalise(one) != _normalise(resp(headers={"set-cookie": "session=abc; path=/"}))
    assert _normalise(one) != _normalise(resp())

    def zipped(text: str, length: str):
        return httpx.Response(
            404,
            content=gzip.compress(text.encode()),
            headers={"content-encoding": "gzip", "content-length": length},
        )

    # compressed lengths are not compared (they vary with the ids inside); bodies are
    assert _normalise(zipped("a", "5")) == _normalise(zipped("a", "6"))
    assert _normalise(zipped("a", "5")) != _normalise(zipped("b", "5"))
    # an id-shaped value under another key is not the correlation id
    assert _normalise(resp('{"detail":"%s"}' % ("a" * 32))) != _normalise(
        resp('{"detail":"%s"}' % ("b" * 32))
    )


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
]


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


async def _run(app, negotiation, method, route, what):
    ids = await _seed(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        signed = await http.post(
            "/api/users/auth/login", data={"username": VIEWER[0], "password": VIEWER[1]}
        )
        assert signed.status_code in (200, 204), signed.text
        # Positive control: the viewer does see the collection, so a 404 below is the gate.
        seen = await http.get(f"/api/images/collections/{ids['cid']}")
        assert seen.status_code == 200, seen.text
        url = route.format(i=ids["iid"], g=ids["gid"], s=ids["slug"])
        if "/public/" in url:
            http.cookies.clear()  # the anonymous twin: no session at all
            # The first anonymous request mints the locale cookie (and its
            # `Vary: Cookie`); take that out of the comparison.
            await http.get("/api/images/public/c/none/images", headers=_negotiate(app, negotiation))
        call = getattr(http, method)
        extra = _negotiate(app, negotiation)
        await call(url, headers=extra)  # the rolling session cookie is refreshed here
        withheld = await call(url, headers=extra)
        await _delete(app, ids, what)
        await call(url, headers=extra)
        absent = await call(url, headers=extra)
        _expect_shape(negotiation, withheld, method, url)
        _expect_shape(negotiation, absent, method, url)
        assert _normalise(withheld) == _normalise(absent)
        assert withheld.headers.get("vary") == absent.headers.get("vary")


@pytest.mark.parametrize("negotiation", sorted(NEGOTIATIONS))
@pytest.mark.parametrize(("method", "route"), ROUTES)
def test_withheld_and_absent_look_the_same(host, method, route, negotiation):
    what = "group" if "/groups/" in route else "image"

    async def go():
        async with host.router.lifespan_context(host):
            await _run(host, negotiation, method, route, what)

    asyncio.run(go())
