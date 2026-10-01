"""The ``media`` field picker's backend half: the setting, the detection and
the view props (:mod:`sm_records.media`).

Nothing here imports ``file_storage`` — neither does the module. The "media
library" in these tests is a stand-in router with the same four route shapes
the framework module mounts, which is exactly what detection keys on; a test
that mounted the real one would pass for the wrong reason if detection ever
started importing it.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI, File, UploadFile
from pydantic import ValidationError
from simple_module_core.public_routes import PublicRouteRegistry
from sm_records import media
from sm_records.settings import RecordsSettings
from sm_records.settings_boot import BootSettings

from tests.app_harness import ADMIN, roles, seed_type

_STOCK = "/api/file-storage"
_IMAGE = {
    "key": "image",
    "type": "media",
    "label": "Image",
    "required": False,
    "unique": False,
    "indexed": False,
    "default": None,
    "help": None,
    "constraints": {},
    "options": {},
}
_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


def _media_router(*, upload: bool = True, search: bool = False) -> APIRouter:
    """``file_storage``'s route table, minus everything but the shapes."""
    router = APIRouter()
    if upload:

        @router.post("/upload", status_code=201)
        async def upload_file(file: UploadFile = File(...)) -> dict:  # pragma: no cover
            return {}

    if search:

        @router.get("/files")
        async def list_files(page: int = 1, per_page: int = 20, q: str = "") -> dict:
            return {}  # pragma: no cover

    else:

        @router.get("/files")
        async def list_files_plain(page: int = 1, per_page: int = 20) -> dict:
            return {}  # pragma: no cover

    @router.get("/files/{file_id}")
    async def get_file(file_id: str) -> dict:  # pragma: no cover
        return {}

    @router.get("/files/{file_id}/download")
    async def download_file(file_id: str) -> dict:  # pragma: no cover
        return {}

    return router


def _app(*prefixes: str, **router_kwargs) -> FastAPI:
    app = FastAPI()
    for prefix in prefixes:
        app.include_router(_media_router(**router_kwargs), prefix=prefix)
    return app


# ---- The setting ----------------------------------------------------------


def test_the_setting_defaults_to_detection_and_needs_a_restart():
    field = RecordsSettings.model_fields["media_api_prefix"]
    assert RecordsSettings().media_api_prefix is None
    assert field.json_schema_extra == {"requires_restart": True}
    # Declared on the boot-time base, so it sits with the other restart fields.
    assert "media_api_prefix" in BootSettings.model_fields
    assert field.description and "file_storage" in field.description


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("/api/file-storage", "/api/file-storage"),
        ("/media/api/", "/media/api"),
        ("", ""),
        ("  ", ""),
    ],
)
def test_the_setting_normalises_a_path_and_the_off_sentinel(raw, stored):
    assert RecordsSettings(media_api_prefix=raw).media_api_prefix == stored


@pytest.mark.parametrize(
    "raw",
    ["api/files", "/", "//cdn.example.com/api", "https://media.example.com", "/a b", "/a?x=1"],
)
def test_the_setting_refuses_anything_but_a_path_on_this_host(raw):
    with pytest.raises(ValidationError, match="media_api_prefix"):
        RecordsSettings(media_api_prefix=raw)


# ---- Detection ------------------------------------------------------------


def test_detects_the_media_api_by_its_route_shape():
    assert media.detect_prefix(_app(_STOCK)) == _STOCK
    assert media.detect_prefix(_app("/elsewhere/files-api")) == "/elsewhere/files-api"


def test_no_media_api_means_no_prefix():
    assert media.detect_prefix(FastAPI()) is None


def test_a_partial_match_is_not_a_media_api():
    """Three of the four routes is somebody else's ``/files`` API."""
    assert media.detect_prefix(_app(_STOCK, upload=False)) is None


def test_two_media_apis_need_the_operator_to_choose(caplog):
    app = _app(_STOCK, "/api/other-files")
    with caplog.at_level(logging.WARNING, logger="sm_records.media"):
        assert media.detect_prefix(app) is None
    assert "media_api_prefix" in caplog.text


def test_the_registered_file_storage_module_breaks_a_tie():
    app = _app("/api/other-files", _STOCK)
    meta = SimpleNamespace(name=media.MEDIA_MODULE_NAME, route_prefix=_STOCK)
    app.state.sm = SimpleNamespace(modules=(SimpleNamespace(meta=meta),))
    assert media.detect_prefix(app) == _STOCK


def test_a_search_parameter_on_the_list_route_is_picked_up():
    assert media.resolve(_app(_STOCK), None).search_param is None
    assert media.resolve(_app(_STOCK, search=True), None).search_param == "q"


def test_files_are_public_only_when_the_registry_exempts_the_download():
    app = _app(_STOCK)
    app.state.public_routes = PublicRouteRegistry()
    assert media.resolve(app, None).public_files is False
    app.state.public_routes.add_prefix(f"{_STOCK}/files/", methods={"GET"})
    assert media.resolve(app, None).public_files is True


def test_the_props_name_every_path_the_browser_calls():
    assert media.MediaApi(prefix=_STOCK).props() == {
        "prefix": _STOCK,
        "list_path": f"{_STOCK}/files",
        "upload_path": f"{_STOCK}/upload",
        "file_url_template": f"{_STOCK}/files/{{id}}/download",
        "meta_url_template": f"{_STOCK}/files/{{id}}",
        "search_param": None,
    }


# ---- The setting, applied -------------------------------------------------


def test_an_empty_setting_turns_the_picker_off_even_with_a_library():
    assert media.resolve(_app(_STOCK), "") is None


def test_an_explicit_prefix_is_used_even_when_nothing_is_mounted_there(caplog):
    with caplog.at_level(logging.WARNING, logger="sm_records.media"):
        resolved = media.resolve(FastAPI(), "/proxied/media")
    assert resolved is not None and resolved.prefix == "/proxied/media"
    assert "does not match" in caplog.text


def test_an_invalid_stored_prefix_falls_back_to_detection(caplog):
    """Refused at save — but ``on_startup`` must not raise over a stored row."""
    with caplog.at_level(logging.ERROR, logger="sm_records.media"):
        resolved = media.resolve(_app(_STOCK), "https://evil.example.com")
    assert resolved is not None and resolved.prefix == _STOCK
    assert "invalid" in caplog.text


# ---- Through on_startup, into the screens -----------------------------------


async def _started(client, *, mount: bool, prefix: str | None = None):
    app = client.app
    if mount:
        app.include_router(_media_router(), prefix=_STOCK)
    module = app.state.records_module
    if prefix is not None:
        module.settings = RecordsSettings(media_api_prefix=prefix)
        app.state.sm_records.settings = module.settings
    await module.on_startup(app)
    return app


async def _props(client, path: str) -> dict:
    resp = await client.get(path, headers={**roles(ADMIN), **_INERTIA})
    assert resp.status_code == 200, resp.text
    return resp.json()["props"]


async def test_the_editor_and_list_carry_the_detected_media_api(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "product", [_IMAGE])
    await _started(client, mount=True)

    expected = media.MediaApi(prefix=_STOCK).props()
    assert (await _props(client, "/admin/records/product/new"))["media_api"] == expected
    assert (await _props(client, "/admin/records/product"))["media_api"] == expected


async def test_no_media_library_means_a_null_prop(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "product", [_IMAGE])
    await _started(client, mount=False)

    assert (await _props(client, "/admin/records/product/new"))["media_api"] is None
    assert (await _props(client, "/admin/records/product"))["media_api"] is None


async def test_the_setting_wins_over_detection_at_startup(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "product", [_IMAGE])
    await _started(client, mount=True, prefix="")
    assert (await _props(client, "/admin/records/product/new"))["media_api"] is None


async def test_the_public_listing_advertises_a_file_url_only_for_anonymous_files(
    client, records_app
):
    app = await _started(client, mount=True)
    resp = await client.post(
        "/api/records/types",
        json={
            "key": "gallery",
            "label": "Gallery",
            "is_public": True,
            "fields": [{"key": "image", "type": "media", "label": "Image"}],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    listed = await client.get("/api/records/public/gallery")
    assert listed.json()["media_url_template"] is None

    registry = PublicRouteRegistry()
    registry.add_prefix(f"{_STOCK}/files/", methods={"GET"})
    app.state.public_routes = registry
    await app.state.records_module.on_startup(app)
    listed = await client.get("/api/records/public/gallery")
    assert listed.json()["media_url_template"] == f"{_STOCK}/files/{{id}}/download"
