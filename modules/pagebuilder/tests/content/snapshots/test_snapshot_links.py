"""An uploaded bundle meets the block-link rule an API save does (#354).

A bundle is content from outside the site, so a ``javascript:`` link in a
page's draft or published data, or in the layout, is refused at upload. The
``asset://`` sentinel capture writes for a media URL is not a refused scheme.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from pagebuilder.content.links import UnsafeLinkError, check_links
from pagebuilder.content.snapshots.archive import BundleError, read_zip
from pagebuilder.content.snapshots.blobs import BlobStore


def _bundle(files: dict[str, bytes]) -> bytes:
    base = {
        "manifest.json": json.dumps({"format_version": 1}).encode(),
        "media/index.json": b"{}",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (base | files).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _doc(href: str) -> dict:
    return {"content": [{"type": "Button", "props": {"id": "B-1", "href": href}}]}


def _page(**data: dict) -> bytes:
    return json.dumps({"slug": "home", "status": "draft", **data}).encode()


def _read(tmp_path, files: dict[str, bytes]) -> None:
    read_zip(_bundle(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


@pytest.mark.parametrize("field", ["draft_data", "published_data"])
def test_a_page_with_an_unsafe_link_is_refused(tmp_path, field):
    files = {"pages/home.json": _page(**{field: _doc("javascript:alert(1)")})}
    with pytest.raises(BundleError, match=rf"pages/home.json {field}: Block Button \(B-1\)"):
        _read(tmp_path, files)


def test_a_layout_with_an_unsafe_link_is_refused(tmp_path):
    layout = json.dumps({"header_data": _doc("data:text/html,x"), "footer_data": {}}).encode()
    with pytest.raises(BundleError, match=r"layout.json header_data: Block Button"):
        _read(tmp_path, {"layout.json": layout})


def test_safe_links_pass(tmp_path):
    _read(tmp_path, {"pages/home.json": _page(draft_data=_doc("/about"))})
    assert (tmp_path / "out" / "pages" / "home.json").is_file()


def test_the_asset_sentinel_is_admitted_only_for_a_bundle():
    """Capture writes a media URL as ``asset://<name>``; apply resolves it back."""
    check_links(_doc("asset://brochure.pdf"), extra_schemes=("asset",))
    with pytest.raises(UnsafeLinkError):
        check_links(_doc("asset://brochure.pdf"))
