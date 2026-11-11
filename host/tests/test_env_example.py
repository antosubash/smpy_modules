"""`.env.example` ships no secret values, and `make env` generates every one (#352).

The file used to carry placeholder secrets. The repo's own wording passed the
framework's checks, which refuse only their own placeholders, so a hand-copied
file booted in production with a session key and token-signing keys anyone
could read here. Shipping no value at all leaves nothing to keep by mistake:
without the users module's two token secrets production refuses to boot, and
without ``SM_SECRET_KEY`` the host generates its own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from simple_module_core.dotenv import parse_dotenv

ROOT = Path(__file__).resolve().parents[2]
SECRETS = (
    "SM_SECRET_KEY",
    "SM_USERS_RESET_PASSWORD_TOKEN_SECRET",
    "SM_USERS_VERIFICATION_TOKEN_SECRET",
)


@pytest.mark.parametrize("key", SECRETS)
def test_the_example_sets_no_secret(key: str) -> None:
    assert key not in parse_dotenv(ROOT / ".env.example")


def test_make_env_generates_every_secret() -> None:
    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^env:\n((?:\t.*\n)+)", makefile, re.M)
    assert recipe, "Makefile has no env target"
    for key in SECRETS:
        assert f"'{key}'" in recipe.group(1), f"make env does not generate {key}"
