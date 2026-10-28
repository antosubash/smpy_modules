"""``sm_images.urls``: where a rendition is fetched from (Task 12)."""

from __future__ import annotations

import uuid

import pytest
from sm_images import contracts, urls
from sm_images.models import Image, Visibility
from sm_images.module import ImagesModule

from tests.access_support import collection

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
        storage_key="k",
        filename="f",
        content_type="image/jpeg",
        size_bytes=1,
        display_generation=generation,
    )


def _coll(visibility: Visibility):
    coll = collection("trees", visibility)
    coll.id = uuid.UUID(int=5)
    return coll


def test_rendition_url_is_the_admin_route_versioned_by_display_generation():
    img = _image(_coll(Visibility.PUBLIC))
    assert urls.rendition_url(img, "small") == f"/api/images/images/{img.id}/r/small?v=2"
    assert contracts.rendition_url(img, "small") == urls.rendition_url(img, "small")


def test_a_new_display_generation_is_a_new_url():
    coll = _coll(Visibility.PRIVATE)
    assert urls.rendition_url(_image(coll, 2), "s") != urls.rendition_url(_image(coll, 3), "s")


def test_public_asset_base_fronts_only_public_collections():
    urls.configure(CDN + "/")
    pub, priv = _coll(Visibility.PUBLIC), _coll(Visibility.PRIVATE)
    img = _image(pub)
    assert urls.rendition_url(img, "small", collection=pub) == (
        f"{CDN}/api/images/public/c/trees/images/{img.id}/r/small?v=2"
    )
    assert contracts.rendition_url(img, "small", collection=pub).startswith(CDN)
    for coll in (priv, _coll(Visibility.INTERNAL)):
        other = _image(coll)
        assert urls.rendition_url(other, "small", collection=coll).startswith("/api/images/images/")
    # No collection named: the base cannot be used, the admin route is.
    assert urls.rendition_url(img, "small").startswith("/api/images/images/")


def test_public_rendition_url_is_the_twin_and_refuses_a_non_public_collection():
    pub = _coll(Visibility.PUBLIC)
    img = _image(pub)
    assert urls.public_rendition_url(pub, img, "small") == (
        f"/api/images/public/c/trees/images/{img.id}/r/small?v=2"
    )
    with pytest.raises(ValueError):
        urls.public_rendition_url(_coll(Visibility.PRIVATE), _image(pub), "small")


def test_a_collection_that_does_not_hold_the_image_is_refused():
    pub = _coll(Visibility.PUBLIC)
    stray = _image(pub)
    stray.collection_id = uuid.uuid4()
    with pytest.raises(ValueError):
        urls.rendition_url(stray, "small", collection=pub)


def test_the_size_is_escaped():
    img = _image(_coll(Visibility.PRIVATE))
    assert urls.rendition_url(img, "a/b?c").startswith(f"/api/images/images/{img.id}/r/a%2Fb%3Fc?")


async def test_on_startup_reads_the_public_asset_base(images_app):
    app, _ = images_app
    app.state.sm_images.settings.public_asset_base_url = CDN
    await ImagesModule().on_startup(app)
    pub = _coll(Visibility.PUBLIC)
    assert urls.rendition_url(_image(pub), "small", collection=pub).startswith(CDN)
