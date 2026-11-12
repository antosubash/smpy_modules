"""``reencrypt_secrets.py`` rotates, upgrades and seals, all or nothing (#351),
and ``set_setting.py`` stores records' CAPTCHA secret encrypted (#350).

Each run is a subprocess against a private copy of a migrated SQLite database,
with ``SM_PROJECT_ROOT`` pointed at an empty directory so the repo's own
``.env`` supplies nothing.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import reencrypt_support as rs  # noqa: E402

OLD, NEW = "the-old-secret-key", "the-new-secret-key"
AI_KEY, BILLING_KEY = "sm_ai.chat_api_key", "sm_billing.stripe_secret_key"
SMTP_KEY = "sm_newsletter.smtp_password"
CAPTCHA_KEY = "sm_records.public_submissions_captcha_secret"
PLAIN = {AI_KEY: "sk-ant-1", BILLING_KEY: "sk_test_1", SMTP_KEY: "smtp-pw", CAPTCHA_KEY: "cap-1"}


@pytest.fixture
def db(_migrated, tmp_path) -> Path:
    copy = tmp_path / "host.db"
    copy.write_bytes(_migrated.read_bytes())
    return copy


def _crypto(package: str, secret: str):
    module = rs.crypto_for(package)
    module.set_secret_provider(lambda: secret)
    return module


def _v1(plain: str, secret: str) -> str:
    key = urlsafe_b64encode(sha256(secret.encode()).digest())
    return "enc:v1:" + Fernet(key).encrypt(plain.encode()).decode()


def _put(db: Path, key: str, value: str, value_type: str = "string") -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO settings_setting (scope, scope_id, key, value, value_type) "
            "VALUES ('system', '', ?, ?, ?)",
            (key, value, value_type),
        )


def _stored(db: Path) -> dict[str, tuple[str, str]]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT key, value, value_type FROM settings_setting").fetchall()
    return {key: (value, value_type) for key, value, value_type in rows}


def _run(db: Path, tmp_path: Path, *args: str, previous: str | None = OLD, key: str | None = NEW):
    root = tmp_path / "project"  # the host's templates, but no .env
    if not root.exists():
        root.mkdir()
        (root / "host").symlink_to(REPO / "host")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SM_SECRET_KEY")}
    env |= {"SM_DATABASE_URL": f"sqlite+aiosqlite:///{db}", "SM_PROJECT_ROOT": str(root)}
    if key is not None:
        env["SM_SECRET_KEY"] = key
    if previous is not None:
        env["SM_SECRET_KEY_PREVIOUS"] = previous
    return subprocess.run(
        [sys.executable, *args], cwd=REPO, env=env, capture_output=True, text=True, check=False
    )


def _reencrypt(db: Path, tmp_path: Path, *flags: str, **kw):
    return _run(db, tmp_path, "scripts/reencrypt_secrets.py", *flags, **kw)


def _seed(db: Path) -> None:
    """One row of each kind: a v2 under the old key, a v1, plaintext (string and json)."""
    _put(db, AI_KEY, _crypto("sm_ai", OLD).encrypt_value(PLAIN[AI_KEY]))
    _put(db, BILLING_KEY, _v1(PLAIN[BILLING_KEY], OLD))
    _put(db, SMTP_KEY, PLAIN[SMTP_KEY])
    _put(db, CAPTCHA_KEY, json.dumps(PLAIN[CAPTCHA_KEY]), "json")
    _put(db, "other.thing", "enc:v2:not-ours")


def _decrypt(key: str, stored: tuple[str, str], secret: str) -> str:
    package, _, field = key.partition(".")
    value = json.loads(stored[0]) if stored[1] == "json" else stored[0]
    assert value.startswith("enc:v2:"), key
    return _crypto(package, secret).decrypt_value(value, field)


def test_targets_match_each_modules_constants():
    from sm_ai.core.constants import SECRET_FIELDS as AI
    from sm_billing.core.constants import SECRET_FIELDS as BILLING
    from sm_records.public_submissions.captcha_secret import FIELD as CAPTCHA_FIELD

    assert set(rs.TARGETS["sm_ai"]) == AI
    assert set(rs.TARGETS["sm_billing"]) == BILLING
    assert rs.TARGETS["sm_records"] == (CAPTCHA_FIELD,)


def test_dry_run_writes_nothing_and_prints_no_value(db, tmp_path):
    _seed(db)
    before = _stored(db)
    result = _reencrypt(db, tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert _stored(db) == before
    out = result.stdout + result.stderr
    assert "4 secret(s) would be re-encrypted" in out
    for outcome in (rs.ROTATE, rs.UPGRADE, rs.SEAL):
        assert outcome in out
    assert "other.thing (system) (left untouched)" in out
    for value in [*PLAIN.values(), *(v for v, _ in before.values())]:
        assert value not in out


def test_a_run_rotates_upgrades_and_seals_then_is_a_no_op(db, tmp_path):
    _seed(db)
    result = _reencrypt(db, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Re-encrypted 4 secret(s)" in result.stdout
    stored = _stored(db)
    for key, plain in PLAIN.items():
        assert _decrypt(key, stored[key], NEW) == plain, "opens under the new key alone"
    assert stored[CAPTCHA_KEY][1] == "json"
    assert stored["other.thing"][0] == "enc:v2:not-ours"
    again = _reencrypt(db, tmp_path, previous=None)
    assert again.returncode == 0, again.stderr
    assert "Nothing to re-encrypt" in again.stdout
    assert _stored(db) == stored


def test_one_unreadable_row_writes_nothing(db, tmp_path):
    _seed(db)
    _put(db, "sm_ai.embedding_api_key", _crypto("sm_ai", "a-lost-key").encrypt_value("x"))
    before = _stored(db)
    result = _reencrypt(db, tmp_path)
    assert result.returncode == 1
    assert "sm_ai.embedding_api_key (system)" in result.stdout
    assert "nothing was written" in result.stderr
    assert _stored(db) == before


def test_no_seal_plaintext_keeps_plaintext(db, tmp_path):
    _put(db, SMTP_KEY, PLAIN[SMTP_KEY])
    result = _reencrypt(db, tmp_path, "--no-seal-plaintext")
    assert result.returncode == 0, result.stderr
    assert rs.PLAINTEXT_KEPT in result.stdout
    assert _stored(db)[SMTP_KEY][0] == PLAIN[SMTP_KEY]


def test_a_malformed_previous_refuses_before_writing(db, tmp_path):
    """Even when every row opens with the current key, so none would need it."""
    _put(db, SMTP_KEY, PLAIN[SMTP_KEY])
    before = _stored(db)
    result = _reencrypt(db, tmp_path, previous='["leaky-old-key"')
    assert result.returncode == 1
    assert "SM_SECRET_KEY_PREVIOUS" in result.stderr
    assert "leaky-old-key" not in result.stdout + result.stderr
    assert _stored(db) == before


def test_refuses_without_a_provisioned_key(db, tmp_path):
    _seed(db)
    before = _stored(db)
    result = _reencrypt(db, tmp_path, key=None)
    assert result.returncode != 0
    assert "no secret key provisioned" in result.stderr
    assert _stored(db) == before


def test_a_module_that_is_not_installed_is_an_error(monkeypatch):
    monkeypatch.setattr(rs, "crypto_for", lambda package: None)
    row = rs.Row("system", "", AI_KEY, "enc:v2:x", "string")
    assert rs.plan_row(row).outcome == rs.NOT_INSTALLED
    assert rs.NOT_INSTALLED in rs.ERRORS


def test_a_json_null_is_empty_not_an_error():
    row = rs.Row("system", "", CAPTCHA_KEY, "null", "json")
    assert rs.plan_row(row).outcome == rs.EMPTY


def test_set_setting_stores_the_captcha_secret_encrypted(db, tmp_path):
    result = _run(
        db,
        tmp_path,
        "scripts/set_setting.py",
        "sm_records",
        "public_submissions_captcha_secret",
        json.dumps(PLAIN[CAPTCHA_KEY]),
        previous=None,
    )
    assert result.returncode == 0, result.stderr
    assert PLAIN[CAPTCHA_KEY] not in result.stdout
    stored = _stored(db)[CAPTCHA_KEY]
    assert PLAIN[CAPTCHA_KEY] not in stored[0]
    assert _decrypt(CAPTCHA_KEY, stored, NEW) == PLAIN[CAPTCHA_KEY]


def test_a_missing_secret_is_one_check_before_planning():
    """``run`` checks the current secret once, not per row: ``check_secret``
    raises before ``plan_row`` is ever reached."""
    rs.install_secret("")
    try:
        with pytest.raises(RuntimeError, match=r"(?i)secret"):
            rs.check_secret()
    finally:
        rs.install_secret(NEW)
    rs.check_secret()


def test_a_fresh_database_has_nothing_to_re_encrypt(tmp_path):
    result = _reencrypt(tmp_path / "fresh.db", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Nothing to re-encrypt" in result.stdout


def test_an_orphaned_row_is_not_installed_whatever_it_holds(monkeypatch):
    monkeypatch.setattr(rs, "crypto_for", lambda package: None)
    for value, value_type in (("", "string"), ("[1]", "json"), ("null", "json")):
        row = rs.Row("system", "", AI_KEY, value, value_type)
        assert rs.plan_row(row).outcome == rs.NOT_INSTALLED
