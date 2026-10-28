"""The skeleton's registrations: permissions, settings, public routes, body limits."""

from __future__ import annotations

from types import SimpleNamespace

from simple_module_core.body_limits import BodyLimitRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from sm_images import constants
from sm_images.module import ImagesModule
from sm_images.settings import ImagesSettings

EXPECTED_PERMISSIONS = {
    "images.view",
    "images.create",
    "images.publish",
    "images.manage",
    "images.originals.view",
    "images.settings",
}


def test_module_registers_permissions():
    registry = PermissionRegistry()
    ImagesModule().register_permissions(registry)
    assert set(registry.all_permissions) == EXPECTED_PERMISSIONS
    (group,) = registry.groups
    assert group.name == constants.PERM_GROUP
    assert group.label_key == "images.permission_group"


def test_settings_ignore_env(monkeypatch):
    monkeypatch.setenv("SM_IMAGES_MAX_IMAGE_BYTES", "1")
    monkeypatch.setenv("MAX_IMAGE_BYTES", "1")
    assert ImagesSettings().max_image_bytes == 50 * 2**20
    # Constructor kwargs are the one source: how the hydrator applies stored values.
    assert ImagesSettings(max_image_bytes=7).max_image_bytes == 7


def test_public_routes_get_only():
    registry = PublicRouteRegistry()
    ImagesModule().register_public_routes(registry)
    for prefix in constants.PUBLIC_PREFIXES:
        assert prefix.endswith("/")
        assert registry.matches("GET", f"{prefix}anything")
        assert registry.matches("HEAD", f"{prefix}anything")
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert not registry.matches(method, f"{prefix}anything")
    assert registry.matches("GET", "/images/c/my-collection")
    # The admin API and console are never exempted, whatever the method.
    for path in ("/api/images", "/api/images/collections", "/admin/images/", "/images"):
        assert not registry.matches("GET", path)


def test_body_limits_follow_the_upload_setting():
    registry = BodyLimitRegistry()
    ImagesModule().register_body_limits(registry)
    settings = ImagesSettings(upload_body_max_bytes=123)
    app = SimpleNamespace(state=SimpleNamespace(sm_images=SimpleNamespace(settings=settings)))
    want = 123 + constants.MULTIPART_OVERHEAD_BYTES
    for path in ("/api/images/collections/7/images", "/api/images/uploads/9/parts/1"):
        assert registry.limit_for("POST", path, app) == want
    assert registry.limit_for("GET", "/api/images/collections/7/images", app) is None
    assert registry.limit_for("POST", "/api/images/collections", app) is None


async def test_harness_serves_the_routers(client, storage):
    assert client.app.state.sm_images.settings.batch_max == 50
    assert client.app.state.file_storage.backend is storage
    # The collection routes are mounted, and an anonymous caller is refused.
    assert (await client.get("/api/images/collections")).status_code == 401


async def test_on_startup_installs_the_intent_session_factory(images_app):
    """Handlers call ``object_intent(keys)`` with no factory: ``on_startup`` must
    have set the default to the app's own."""
    from sm_images import intents
    from sm_images.models import ObjectIntent
    from sqlalchemy import select

    app, db_state = images_app
    await ImagesModule().on_startup(app)
    assert intents._default_factory is db_state.session_factory
    async with intents.object_intent(["images/default/boot"]):
        pass
    async with db_state.session_factory() as s:
        assert (await s.execute(select(ObjectIntent.key))).scalars().all() == [
            "images/default/boot"
        ]
