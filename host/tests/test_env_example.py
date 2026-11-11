"""`.env.example` ships the framework's own placeholder secrets.

The framework refuses to boot outside development/testing on exactly these
values: ``SM_SECRET_KEY=change-me-in-production`` in ``BootstrapSettings`` and
the users module's two ``dev-*-token-secret-change-me`` defaults. A placeholder
of the repo's own wording passed both checks, so a hand-copied file booted in
production with a session key and token-signing keys anyone could read here.
A framework that renamed a placeholder fails this test instead of reopening
that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from simple_module_core.dotenv import parse_dotenv
from simple_module_hosting.bootstrap_settings import BootstrapSettings
from users.core import settings as users_settings

EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture(scope="module")
def example() -> dict[str, str]:
    return parse_dotenv(EXAMPLE)


def test_secret_key_placeholder_is_refused_in_production(example: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="SM_SECRET_KEY must be set"):
        BootstrapSettings(
            _env_file=None,
            environment="production",
            secret_key=example["SM_SECRET_KEY"],
        )


def test_users_token_placeholders_are_the_framework_defaults(example: dict[str, str]) -> None:
    assert example["SM_USERS_RESET_PASSWORD_TOKEN_SECRET"] == (
        users_settings._PLACEHOLDER_RESET_SECRET
    )
    assert example["SM_USERS_VERIFICATION_TOKEN_SECRET"] == (
        users_settings._PLACEHOLDER_VERIFY_SECRET
    )
