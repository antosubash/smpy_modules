"""``sm_images.serving.urls``: where a rendition is fetched from (Task 12)."""

from __future__ import annotations

import uuid

import pytest
from sm_images import contracts
from sm_images.models import Image, Rendition, Visibility
from sm_images.module import ImagesModule
from sm_images.serving import cache, urls

from tests.support.access import collection

CDN = "https://cdn.example.org"


@pytest.fixture(autouse=True)
def _no_base():
    urls.configure("")
    yield
    urls.configure("")


def _image(coll, generation: int = 2) -> Image:
    return Image(
        id=uuid.UUID(int=9),
        collection_id=coll.id,
        storage_key="k/original.jpg",
        display_key=f"k/display.{generation}.a.jpg",
        filename="f",
        content_type="image/jpeg",
        size_bytes=1,
        display_generation=generation,
    )


def _rend(img: Image, size: str = "small", key: str | None = None) -> Rendition:
    return Rendition(
        image_id=img.id,
        size=size,
        storage_key=key or f"k/r/{size}.{img.display_generation}.a.jpg",
        width=1,
        height=1,
        source_generation=img.display_generation,
    )


def _coll(visibility: Visibility):
    coll = collection("trees", visibility)
    coll.id = uuid.UUID(int=5)
    return coll


def _v(img: Image, rend: Rendition) -> str:
    return cache.version(rend.source_generation, rend.storage_key)


def test_rendition_url_is_the_admin_route_versioned_by_its_bytes():
    img = _image(_coll(Visibility.PUBLIC))
    rend = _rend(img)
    want = f"/api/images/images/{img.id}/r/small?v={_v(img, rend)}"
    assert urls.rendition_url(img, rend) == want
    assert contracts.rendition_url(img, rend) == want
    assert _v(img, rend).startswith("2.")


def test_a_new_rendition_key_is_a_new_url_even_in_the_same_generation():
    img = _image(_coll(Visibility.PRIVATE))
    a, b = _rend(img, key="k/r/small.2.a.jpg"), _rend(img, key="k/r/small.2.b.jpg")
    assert urls.rendition_url(img, a) != urls.rendition_url(img, b)


def test_display_url_names_the_display_bytes():
    img = _image(_coll(Visibility.PRIVATE))
    v = cache.version(img.display_generation, img.display_key)
    assert urls.display_url(img) == f"/api/images/images/{img.id}/display?v={v}"
    img.display_key = None
    v = cache.version(img.display_generation, img.storage_key)
    assert urls.display_url(img).endswith(f"?v={v}")


def test_public_asset_base_fronts_only_public_collections():
    urls.configure(CDN + "/")
    pub, priv = _coll(Visibility.PUBLIC), _coll(Visibility.PRIVATE)
    img = _image(pub)
    rend = _rend(img)
    assert urls.rendition_url(img, rend, collection=pub) == (
        f"{CDN}/api/images/public/c/trees/images/{img.id}/r/small?v={_v(img, rend)}"
    )
    assert contracts.rendition_url(img, rend, collection=pub).startswith(CDN)
    assert urls.display_url(img, collection=pub).startswith(CDN)
    for coll in (priv, _coll(Visibility.INTERNAL)):
        other = _image(coll)
        got = urls.rendition_url(other, _rend(other), collection=coll)
        assert got.startswith("/api/images/images/")
    # No collection named: the base cannot be used, the admin route is.
    assert urls.rendition_url(img, rend).startswith("/api/images/images/")


def test_public_rendition_url_is_the_twin_and_refuses_a_non_public_collection():
    pub = _coll(Visibility.PUBLIC)
    img = _image(pub)
    rend = _rend(img)
    assert urls.public_rendition_url(pub, img, rend) == (
        f"/api/images/public/c/trees/images/{img.id}/r/small?v={_v(img, rend)}"
    )
    with pytest.raises(ValueError):
        urls.public_rendition_url(_coll(Visibility.PRIVATE), img, rend)


def test_a_collection_or_rendition_that_does_not_belong_is_refused():
    pub = _coll(Visibility.PUBLIC)
    stray = _image(pub)
    rend = _rend(stray)
    stray.collection_id = uuid.uuid4()
    with pytest.raises(ValueError):
        urls.rendition_url(stray, rend, collection=pub)
    img = _image(pub)
    foreign = _rend(img)
    foreign.image_id = uuid.uuid4()
    with pytest.raises(ValueError):
        urls.rendition_url(img, foreign)


def test_the_size_is_escaped():
    img = _image(_coll(Visibility.PRIVATE))
    got = urls.rendition_url(img, _rend(img, size="a/b?c"))
    assert got.startswith(f"/api/images/images/{img.id}/r/a%2Fb%3Fc?")


async def test_on_startup_reads_the_public_asset_base(images_app):
    app, _ = images_app
    app.state.sm_images.settings.public_asset_base_url = CDN
    await ImagesModule().on_startup(app)
    pub = _coll(Visibility.PUBLIC)
    img = _image(pub)
    assert urls.rendition_url(img, _rend(img), collection=pub).startswith(CDN)


def test_a_multi_tenant_host_ignores_the_public_asset_base(caplog):
    """A CDN origin carries no tenant, so on a multi-tenant host every public
    URL behind it would 404 (``bind_public`` resolves none): ignored, with a
    warning at boot."""
    from sm_images.tenancy import TenancyMode

    with caplog.at_level("WARNING", logger="sm_images.serving.urls"):
        urls.configure(CDN, TenancyMode.MULTI)
    assert "public_asset_base_url" in caplog.text
    pub = _coll(Visibility.PUBLIC)
    img = _image(pub)
    rend = _rend(img)
    assert urls.rendition_url(img, rend, collection=pub).startswith("/api/images/images/")
    assert urls.public_rendition_url(pub, img, rend).startswith("/api/images/public/c/")
    caplog.clear()
    urls.configure(CDN, TenancyMode.SINGLE)
    assert not caplog.records
    assert urls.public_display_url(pub, img).startswith(CDN)


async def test_on_startup_ignores_the_base_on_a_multi_tenant_host(images_app, monkeypatch):
    from sm_images import tenancy
    from sm_images.tenancy import TenancyMode

    app, _ = images_app
    app.state.sm_images.settings.public_asset_base_url = CDN
    monkeypatch.setattr(tenancy, "configure", lambda _app: TenancyMode.MULTI)
    await ImagesModule().on_startup(app)
    pub = _coll(Visibility.PUBLIC)
    img = _image(pub)
    assert urls.display_url(img, collection=pub).startswith("/api/images/images/")
