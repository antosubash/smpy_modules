"""Pins on the framework internals the AI module reads (#125).

The module range admits any 0.0.x framework, but a worker resolves the
secret the web app encrypts provider keys under through names the framework
does not promise to keep. Each test here fails, with a message naming the
call site, the moment one of them changes — in CI on the framework bump, not
as an ``AiKeyUnreadableError`` in a production worker.

* ``sm_ai/constants.py`` (``HOST_SETTINGS_PACKAGE`` / ``HOST_SECRET_FIELD``,
  read by ``worker_settings._read``) — where ``simple_module_hosting._secret_key``
  stores a generated key. No public replacement yet (wanted:
  ``resolve_secret_key()``).
* ``sm_ai/crypto.py`` (``explicit_secret``, used by ``worker_settings._hydrate``)
  — that ``BootstrapSettings.secret_key`` is in ``model_fields_set`` only when
  it was actually supplied. No public replacement yet.
"""

from __future__ import annotations

import pytest
from sm_ai import constants, crypto

_CONSTANTS = "sm_ai/constants.py (HOST_SETTINGS_PACKAGE / HOST_SECRET_FIELD)"
_EXPLICIT = "sm_ai/crypto.py (explicit_secret)"


def test_the_generated_secret_is_still_stored_where_a_worker_reads_it():
    try:
        from simple_module_hosting import _preapp_config, _secret_key
    except ImportError as exc:
        pytest.fail(f"{_CONSTANTS}: the framework moved its secret-key store: {exc}")
    field = getattr(_secret_key, "SECRET_KEY_FIELD", None)
    package = getattr(_preapp_config, "HOST_PACKAGE", None)
    assert field == constants.HOST_SECRET_FIELD, (
        f"{_CONSTANTS}: the host stores its generated secret as {field!r}, "
        f"not {constants.HOST_SECRET_FIELD!r}; a worker would decrypt with the wrong key"
    )
    assert package == constants.HOST_SETTINGS_PACKAGE, (
        f"{_CONSTANTS}: the host's settings package is {package!r}, "
        f"not {constants.HOST_SETTINGS_PACKAGE!r}"
    )


def test_bootstrap_settings_still_has_a_secret_key_field():
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    assert "secret_key" in BootstrapSettings.model_fields, (
        f"{_EXPLICIT}: BootstrapSettings has no secret_key field any more"
    )


def test_model_fields_set_tells_a_supplied_secret_from_the_default(monkeypatch):
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    unset = BootstrapSettings(_env_file=None)
    assert "secret_key" not in unset.model_fields_set, (
        f"{_EXPLICIT}: an unset SM_SECRET_KEY now shows in model_fields_set, so the "
        "placeholder default would win over the key the host generated"
    )
    assert crypto.explicit_secret(unset) == ""

    monkeypatch.setenv("SM_SECRET_KEY", "pinned-secret")
    supplied = BootstrapSettings(_env_file=None)
    assert "secret_key" in supplied.model_fields_set, (
        f"{_EXPLICIT}: an explicit SM_SECRET_KEY no longer shows in model_fields_set"
    )
    assert crypto.explicit_secret(supplied) == "pinned-secret"
