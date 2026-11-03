"""Newsletter module - lists live in records; campaigns are sent over SMTP."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import weakref
from pathlib import Path

from fastapi import FastAPI
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from sm_newsletter.core import constants

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class NewsletterModule(ModuleBase):
    meta = ModuleMeta(
        name=constants.MODULE_NAME,
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=list(constants.DEPENDS_ON),
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) - this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # Pre-seeding this is how a test pins settings without a database:
        # ``register_settings`` hands it to the services container instead of
        # the pydantic defaults.
        self.settings = None

    def register_settings(self, app: FastAPI) -> None:
        from simple_module_core.module_settings import register_module_settings

        from sm_newsletter.core import crypto
        from sm_newsletter.core.services import NewsletterServices
        from sm_newsletter.core.settings import NewsletterSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            NewsletterSettings,
            lambda defaults: NewsletterServices(settings=self.settings or defaults),
            # The generic Settings screen links here and refuses writes: it
            # would store ``smtp_password`` in plaintext. PR 3 adds the page.
            manage_url=constants.SETTINGS_URL,
        )

        # The running app's secret wins (hosts may inject it through
        # ``create_app(settings=...)``). Resolved lazily - app.state.sm is
        # assigned after this phase - and through a weakref, because the
        # provider is process-global and must not keep a discarded app alive.
        app_ref = weakref.ref(app)

        def _live_secret() -> str:
            live_app = app_ref()
            if live_app is None:
                return ""
            sm = getattr(live_app.state, "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(_live_secret)

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_newsletter.core.errors import install_exception_handlers

        install_exception_handlers(app)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            constants.PERM_GROUP, list(constants.PERMISSIONS), label_key=constants.PERM_GROUP_KEY
        )

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}
