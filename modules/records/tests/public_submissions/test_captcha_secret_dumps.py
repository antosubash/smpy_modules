"""Where ``SealedSecret`` seals, and where it must not (#350).

Only a dump seals, and only in a process an app installed its secret in. A
process with no app (newsletter's worker hydrates ``RecordsSettings`` through
``settings_for``) dumps without raising, and the framework's reload comparison
never sees a legacy plaintext value change. A decrypt step that fails for any
reason answers 503, never a 500.
"""

from __future__ import annotations

import logging

from settings.core.invalidation import reload_package
from simple_module_core.settings_hydrate import build_settings
from sm_records.core import constants, crypto
from sm_records.core.settings import RecordsSettings
from sm_records.public_submissions import captcha_secret

from tests.public_submissions.test_public_submissions_captcha import ON
from tests.support.submissions_http import configure, contact_type, records_of, send

PLAIN = "legacy-plaintext-secret"
ROWS = {captcha_secret.FIELD: (PLAIN, "string")}


def test_a_worker_style_hydration_and_dump_without_a_provider_does_not_raise(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", None)
    settings = build_settings(RecordsSettings, ROWS, lenient=True)
    copy = settings.model_copy(deep=True)  # what ``settings_for`` hands a task
    assert copy.public_submissions_captcha_secret == PLAIN
    assert settings.model_dump()[captcha_secret.FIELD] == PLAIN
    settings.model_dump_json()


class _Store:
    async def get_overrides(self, package: str) -> dict[str, tuple[str, str]]:
        return dict(ROWS) if package == constants.PACKAGE else {}


async def test_reloading_twice_never_reports_the_secret_changed(site, monkeypatch):
    app = site.app
    published: list[tuple[str, ...]] = []

    async def publish(event) -> None:
        published.append(event.changed)

    monkeypatch.setattr(app.state.sm.event_bus, "publish", publish)
    store = _Store()
    await reload_package(app, app.state.sm.event_bus, store, constants.PACKAGE)
    first = getattr(app.state, constants.PACKAGE).settings
    first.model_dump()  # a dump in between (the write path's) changes nothing held
    await reload_package(app, app.state.sm.event_bus, store, constants.PACKAGE)
    assert all(captcha_secret.FIELD not in changed for changed in published[1:])
    assert getattr(app.state, constants.PACKAGE).settings.public_submissions_captcha_secret == PLAIN


async def test_any_decrypt_failure_is_a_503_and_logs_only_the_type(
    site, provider, monkeypatch, caplog
):
    def broken(settings):
        raise OSError(f"cannot read {PLAIN}")

    monkeypatch.setattr(captcha_secret, "secret", broken)
    configure(site, **{**ON, captcha_secret.FIELD: PLAIN})
    await contact_type(site)
    with caplog.at_level(logging.DEBUG):
        refused = await send(site, captcha_response="good")
    assert refused.status_code == 503 and refused.json()["code"] == "captcha_unavailable"
    assert provider.asked == [] and await records_of(site) == []
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "OSError" in logged and PLAIN not in logged


def test_a_provider_whose_app_is_gone_dumps_without_raising(monkeypatch):
    """The provider holds its app weakly and answers "" once it is collected."""
    import gc

    from fastapi import FastAPI

    monkeypatch.setattr(crypto, "_secret_provider", None)
    app = FastAPI()
    captcha_secret.install_secret_provider(app)
    del app
    gc.collect()
    assert crypto._secret_provider is not None and crypto._secret_provider() == ""
    assert not crypto.has_secret_provider()
    settings = build_settings(RecordsSettings, ROWS, lenient=True)
    assert settings.model_dump()[captcha_secret.FIELD] == PLAIN


async def test_the_startup_seal_reaches_the_module_instance_too(site, monkeypatch):
    services = getattr(site.app.state, constants.PACKAGE)
    held = configure(site, **{**ON, captcha_secret.FIELD: PLAIN})
    db = type("Db", (), {"session_factory": None})()
    module = type("M", (), {"db": db, "settings": held})()

    async def sealed(_factory):
        return crypto.encrypt_value(PLAIN)

    monkeypatch.setattr(captcha_secret, "seal_stored", sealed)
    await captcha_secret.seal_at_startup(site.app, module)
    assert module.settings is services.settings
    assert services.settings.public_submissions_captcha_secret.startswith(crypto.ENC_V2)
    assert captcha_secret.secret(module.settings) == PLAIN
