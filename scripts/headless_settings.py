"""The settings a headless script builds its app with: the host's, minus a new key.

``set_setting.py`` and ``seed_usage.py`` construct the app (not start it) and
must see the same modules ``host/main.py`` boots, so they build their settings
the same way, with the framework's ``merge_host_settings`` (#260). That call
also resolves the session-signing key, and when neither the environment
(``.env`` included) nor the database has one, it *generates and commits* a
``host.secret_key`` row. The framework offers no merge that skips that write
(``strict=False`` only relaxes the failure handling).

A one-off command must not provision a deployment's key as a side effect: run
from a shell without ``SM_SECRET_KEY`` against a database whose server gets
its key from the environment, it would leave a row that the next boot without
that variable adopts — every session signed out and ai's stored credentials
undecryptable. So without a key in the environment or the database this
refuses before anything is written; with one, ``merge_host_settings`` reuses
it and writes nothing.
"""

from __future__ import annotations

from simple_module_hosting import Settings, merge_host_settings
from simple_module_hosting._preapp_config import load_host_overrides
from simple_module_hosting.bootstrap_settings import BootstrapSettings

SECRET_KEY_FIELD = "secret_key"
NO_KEY_MESSAGE = (
    "no secret key provisioned: set SM_SECRET_KEY or boot the app once, so this "
    "command does not create the deployment's session key as a side effect"
)


def has_provisioned_key(bootstrap: BootstrapSettings) -> bool:
    """Whether the environment or the database already holds the signing key.

    The environment check is the one ``merge_host_settings`` applies: a value
    ``BootstrapSettings`` was given from ``SM_SECRET_KEY`` or ``.env``. The
    database read is strict, so an unreachable database is reported as such
    rather than as a missing key.
    """
    if SECRET_KEY_FIELD in bootstrap.model_fields_set and bootstrap.secret_key:
        return True
    stored = load_host_overrides(bootstrap.database_url, strict=True)
    raw, _value_type = stored.get(SECRET_KEY_FIELD, (None, None))
    return bool(raw)


def headless_settings(bootstrap: BootstrapSettings | None = None) -> Settings:
    """``merge_host_settings()``, refusing when it would have to create a key."""
    bootstrap = bootstrap or BootstrapSettings()
    if not has_provisioned_key(bootstrap):
        raise SystemExit(NO_KEY_MESSAGE)
    return merge_host_settings(bootstrap)
