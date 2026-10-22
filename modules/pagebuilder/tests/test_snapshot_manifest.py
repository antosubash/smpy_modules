"""The versioned bundle manifest (#79): what export writes, what import accepts."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from page_helpers import create_draft
from pagebuilder.snapshots.archive import BundleError, read_zip
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.format import FORMAT_VERSION
from pagebuilder.snapshots.manifest import (
    FORMAT_MINOR,
    FORMAT_NAME,
    PAGEBUILDER_PATHS,
    check_manifest,
    manifest_header,
)

_SNAPSHOTS = "/api/pagebuilder/snapshots"


def _zip(manifest: dict | None, **files: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if manifest is not None:
            archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("media/index.json", b"{}")
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _section(name: str, **extra) -> dict:
    return {"section": name, "version": 1, **extra}


# --- the writer -------------------------------------------------------------


def test_the_header_names_format_source_tenant_and_contents():
    header = manifest_header("acme")
    assert header["format"] == FORMAT_NAME
    assert header["format_version"] == FORMAT_VERSION
    assert header["format_minor"] == FORMAT_MINOR
    assert header["created_at"]
    assert header["source"]["module"] == "pagebuilder"
    assert header["source"]["package"] == "simple_module_pagebuilder"
    assert header["source"]["version"]
    assert header["tenant"] == "acme"
    [section] = header["contents"]
    assert section == {
        "section": "pagebuilder",
        "version": 1,
        "required": True,
        "paths": list(PAGEBUILDER_PATHS),
    }
    # What this build writes, this build reads.
    assert check_manifest(header)["format_version"] == FORMAT_VERSION


@pytest.mark.asyncio
async def test_a_snapshot_carries_the_header(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    response = await authed_client.post(_SNAPSHOTS, json={})
    assert response.status_code == 201, response.text
    manifest = response.json()["manifest"]
    assert manifest["format"] == FORMAT_NAME
    assert manifest["format_minor"] == FORMAT_MINOR
    assert manifest["tenant"] == "default"
    assert [s["section"] for s in manifest["contents"]] == ["pagebuilder"]
    # The pre-existing keys are still there for older readers and the UI.
    assert manifest["counts"]["pages"] == 1


# --- backward compatibility -------------------------------------------------


@pytest.mark.parametrize("version", [1, 2])
def test_a_manifest_written_before_versioning_still_reads(version):
    assert check_manifest({"format_version": version})["format_version"] == version


def test_an_unversioned_manifest_reads_as_version_1():
    assert check_manifest({"pages": []})["format_version"] == 1


def test_an_unversioned_zip_uploads_as_version_1(tmp_path):
    manifest, _ = read_zip(_zip({}), tmp_path / "out", BlobStore(tmp_path / "blobs"))
    assert manifest["format_version"] == 1


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("version", [3, 99, 0, "2", True, None, 2.0])
def test_an_unknown_major_is_refused(version):
    with pytest.raises(BundleError, match="unsupported bundle format version"):
        check_manifest({"format_version": version})


def test_a_different_format_name_is_refused():
    with pytest.raises(BundleError, match="not a content bundle"):
        check_manifest({"format": "something-else", "format_version": 2})


def test_an_unknown_required_section_is_refused():
    manifest = {"format_version": 2, "contents": [_section("pagebuilder"), _section("news")]}
    with pytest.raises(BundleError, match="requires the 'news' section"):
        check_manifest(manifest)


def test_an_unknown_optional_section_is_ignored():
    news = _section("news", required=False, paths=["news/"])
    manifest = {"format_version": 2, "contents": [_section("pagebuilder"), news]}
    assert check_manifest(manifest)["contents"][1]["section"] == "news"


def test_an_optional_section_may_not_claim_pagebuilder_paths():
    news = _section("news", required=False, paths=["pages/"])
    manifest = {"format_version": 2, "contents": [_section("pagebuilder"), news]}
    with pytest.raises(BundleError, match="outside news/"):
        check_manifest(manifest)


def test_an_unknown_pagebuilder_section_version_is_refused():
    manifest = {"format_version": 2, "contents": [_section("pagebuilder", version=2)]}
    with pytest.raises(BundleError, match="version 2 of the 'pagebuilder' section"):
        check_manifest(manifest)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("pages", "not a list"),
        ([], "no pagebuilder section"),
        (["pagebuilder"], "not an object"),
        ([{"section": "Bad Name", "version": 1}], "valid section name"),
        ([_section("pagebuilder"), _section("pagebuilder")], "twice"),
        ([{"section": "pagebuilder"}], "integer version"),
        ([_section("pagebuilder", required="yes")], "non-boolean"),
        ([_section("pagebuilder", paths="pages/")], "list of strings"),
    ],
)
def test_malformed_contents_are_refused(contents, message):
    with pytest.raises(BundleError, match=message):
        check_manifest({"format_version": 2, "contents": contents})


@pytest.mark.asyncio
async def test_an_unknown_major_upload_is_a_422(authed_client):
    response = await authed_client.post(
        f"{_SNAPSHOTS}/upload",
        files={"file": ("b.zip", _zip({"format_version": 3}), "application/zip")},
    )
    assert response.status_code == 422
    assert "format version 3" in response.json()["detail"]
    assert (await authed_client.get(_SNAPSHOTS)).json()["items"] == []


@pytest.mark.asyncio
async def test_an_upload_records_the_bundles_own_major(authed_client):
    response = await authed_client.post(
        f"{_SNAPSHOTS}/upload",
        files={"file": ("b.zip", _zip({"format_version": 1}), "application/zip")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["format_version"] == 1
