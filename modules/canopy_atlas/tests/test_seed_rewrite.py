"""Asset-path rewriting is the seed's whole contract with the rest of the app.

Photographs must land in the media library so an editor can swap them; the SVG
marks must not, because the library rejects SVG (it can carry script and is
served same-origin); and in-site links must survive untouched.
"""

from __future__ import annotations

from canopy_atlas.seed.uploads import rewrite_asset_paths

UPLOADS = {"/gca/images/hero-lidar.jpg": "/media/pagebuilder/abc.jpg"}


def test_photographs_become_media_library_urls() -> None:
    node = {"props": {"imageUrl": "/gca/images/hero-lidar.jpg"}}
    assert rewrite_asset_paths(node, UPLOADS)["props"]["imageUrl"] == "/media/pagebuilder/abc.jpg"


def test_svg_marks_move_to_the_module_static_mount() -> None:
    node = ["/gca/logo-main.svg", "/gca/logo-reversed.svg", "/gca/partners/iiasa.svg"]
    assert rewrite_asset_paths(node, UPLOADS) == [
        "/canopy-atlas/static/gca/logo-main.svg",
        "/canopy-atlas/static/gca/logo-reversed.svg",
        "/canopy-atlas/static/gca/partners/iiasa.svg",
    ]


def test_in_site_links_are_left_alone() -> None:
    # The rewriter resolves asset paths and nothing else. Page routes are
    # stored the way they are served — "/p/<slug>" — so there is nothing here
    # to translate. "/gca/contact" is GeoWiki's old route for the same page and
    # is *not* rewritten into a working one: content carrying it would 404, so
    # it is caught in the content itself (see test_seed_content.py) rather than
    # papered over at seed time.
    assert rewrite_asset_paths("/p/contact", UPLOADS) == "/p/contact"
    assert rewrite_asset_paths("/gca/contact", UPLOADS) == "/gca/contact"


def test_rewrites_through_nested_structures() -> None:
    node = {"content": [{"props": {"items": [{"src": "/gca/partners/esa.svg"}]}}]}
    out = rewrite_asset_paths(node, UPLOADS)
    assert out["content"][0]["props"]["items"][0]["src"] == (
        "/canopy-atlas/static/gca/partners/esa.svg"
    )


def test_an_unknown_photograph_is_left_alone() -> None:
    # A path the upload step failed on must stay visible as a broken image
    # rather than silently becoming something else.
    assert rewrite_asset_paths("/gca/images/missing.jpg", UPLOADS) == "/gca/images/missing.jpg"
