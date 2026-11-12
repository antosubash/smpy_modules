"""What ``reencrypt_secrets.py`` rewrites, and how it decides (#351).

Kept apart from the command so the decisions can be tested without a database:
which settings rows hold an encrypted secret, which copy of the stored-secret
crypto owns each, and what each row needs.

The targets are listed here rather than read from the installed modules, so a
row left behind by a module that is no longer installed is still found (and
reported, since nothing can decrypt it). ``scripts/tests`` checks ai's,
billing's and records' lists against their modules' own constants; newsletter
has no such constant (its one field is ``smtp_password``).
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from types import ModuleType
from typing import Final

TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "sm_ai": ("chat_api_key", "embedding_api_key"),
    "sm_billing": ("stripe_secret_key", "stripe_webhook_secret"),
    "sm_newsletter": ("smtp_password",),
    "sm_records": ("public_submissions_captcha_secret",),
}
"""``package → fields`` stored as ``enc:``. Every scope is scanned, because the
settings table allows one; in practice they are SYSTEM rows."""

# Outcomes. The first two need nothing; the next three are rewritten; the last
# two stop the whole run.
EMPTY: Final = "empty"
CURRENT: Final = "current"
ROTATE: Final = "rotate"
UPGRADE: Final = "upgrade"
SEAL: Final = "seal"
PLAINTEXT_KEPT: Final = "plaintext (kept)"
UNREADABLE: Final = "unreadable"
NOT_INSTALLED: Final = "module not installed"

REWRITES: Final = frozenset({ROTATE, UPGRADE, SEAL})
ERRORS: Final = frozenset({UNREADABLE, NOT_INSTALLED})


@dataclass(frozen=True)
class Row:
    scope: str
    scope_id: str
    key: str
    value: str
    value_type: str

    @property
    def package(self) -> str:
        return self.key.partition(".")[0]

    @property
    def field(self) -> str:
        return self.key.partition(".")[2]

    def where(self) -> str:
        """How the row is named in output — never with its value."""
        scope = self.scope if not self.scope_id else f"{self.scope}:{self.scope_id}"
        return f"{self.key} ({scope})"


@dataclass(frozen=True)
class Plan:
    row: Row
    outcome: str
    new_value: str | None = None  # the encoded column value to write


def target_keys() -> list[str]:
    return [f"{package}.{field}" for package, fields in TARGETS.items() for field in fields]


def crypto_for(package: str) -> ModuleType | None:
    """The package's own crypto copy, imported directly — so a module that is
    installed but not enabled is still handled — or ``None`` if not installed."""
    try:
        return importlib.import_module(f"{package}.core.crypto")
    except ModuleNotFoundError:
        return None


def install_secret(secret: str) -> None:
    """Make every installed copy encrypt under ``secret`` (the app's key)."""
    for package in TARGETS:
        crypto = crypto_for(package)
        if crypto is not None:
            crypto.set_secret_provider(lambda: secret)


def _decode(row: Row) -> str | None:
    """The stored string, or ``None`` for a json row that does not hold one."""
    if row.value_type != "json":
        return row.value
    try:
        value = json.loads(row.value)
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _encode(row: Row, value: str) -> str:
    return json.dumps(value) if row.value_type == "json" else value


def plan_row(row: Row, *, seal_plaintext: bool = True) -> Plan:
    """What ``row`` needs. Never raises for a bad value; the plan says so."""
    crypto = crypto_for(row.package)
    stored = _decode(row)
    if stored is None:
        return Plan(row, UNREADABLE)
    if not stored:
        return Plan(row, EMPTY)
    if crypto is None:
        return Plan(row, NOT_INSTALLED)
    if not crypto.is_encrypted(stored) and not seal_plaintext:
        return Plan(row, PLAINTEXT_KEPT)
    try:
        new = crypto.reencrypt_value(stored, row.field)
    except RuntimeError:
        raise  # no secret, or an unreadable SM_SECRET_KEY_PREVIOUS: stop the run
    except Exception:  # each copy raises its own unreadable error
        return Plan(row, UNREADABLE)
    if new is None:
        return Plan(row, CURRENT)
    if stored.startswith(crypto.ENC_V2):
        outcome = ROTATE
    elif stored.startswith(crypto.ENC_V1):
        outcome = UPGRADE
    else:
        outcome = SEAL
    return Plan(row, outcome, _encode(row, new))


def looks_encrypted(value: str) -> bool:
    """A stored value carrying an ``enc:`` prefix, plain or as a JSON string."""
    return value.startswith(("enc:", '"enc:'))
