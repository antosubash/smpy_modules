"""The image subject: who an image's billing bills (#284)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sm_images.core import billing
from sm_images.core.billing import subject
from sm_images.pipeline import worker_runtime as wr

OWNER = str(uuid.uuid4())


def _collection(owner_id):
    return SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id)


def _unbillable(caplog):
    return [r for r in caplog.records if "images.billing.owner_unbillable" in r.message]


@pytest.fixture(autouse=True)
def _fresh_log():
    subject.reset_unbillable_log()


def test_tenant_mode_is_the_tenant():
    assert subject.image_subject("default", OWNER, "tenant") == "default"


def test_user_mode_is_the_owner():
    assert subject.image_subject("default", OWNER, "user") == f"user:{OWNER}"
    assert subject.image_subject("default", OWNER.upper(), "user") == f"user:{OWNER}"


@pytest.mark.parametrize("owner", [None, "", "olga"])
def test_malformed_owner_falls_back_once(owner, caplog):
    cid = uuid.uuid4()
    with caplog.at_level("WARNING"):
        assert subject.image_subject("default", owner, "user", collection_id=cid) == "default"
        assert subject.image_subject("default", owner, "user", collection_id=cid) == "default"
    assert len(_unbillable(caplog)) == 1


async def test_owner_subject_deleted_owner_falls_back(monkeypatch, caplog):
    async def gone(db, s):
        return False

    monkeypatch.setattr(subject, "user_exists", gone)
    coll = _collection(OWNER)
    with caplog.at_level("WARNING"):
        assert await subject.owner_subject(None, "default", coll, "user") == "default"
        assert await subject.owner_subject(None, "default", coll, "user") == "default"
    assert len(_unbillable(caplog)) == 1


async def test_owner_subject_existing_owner(monkeypatch):
    async def there(db, s):
        return True

    monkeypatch.setattr(subject, "user_exists", there)
    got = await subject.owner_subject(None, "default", _collection(OWNER), "user")
    assert got == f"user:{OWNER}"


async def test_owner_subject_tenant_mode_runs_no_query():
    def boom():
        raise AssertionError("tenant mode must open no session")

    assert await subject.owner_subject(None, "t", _collection(OWNER), "tenant") == "t"
    assert await subject.owner_subject_in(boom, "t", _collection(OWNER), "tenant") == "t"


async def test_owner_subject_in_reads_in_its_own_session(monkeypatch, pipe):
    seen = []

    async def there(db, s):
        seen.append(db)
        return True

    monkeypatch.setattr(subject, "user_exists", there)
    got = await subject.owner_subject_in(
        pipe.db_state.session_factory, "default", _collection(OWNER), "user"
    )
    assert got == f"user:{OWNER}"
    assert len(seen) == 1


def test_held_under():
    assert subject.held_under("default", None) == "default"
    assert subject.held_under("default", "user:x") == "user:x"


def test_no_billing_is_tenant():
    app = SimpleNamespace(state=SimpleNamespace(billing_subject_mode="user"))
    assert subject.app_mode(app) == "tenant"
    assert subject.worker_mode() == "tenant"


def test_worker_mode_reads_billing(monkeypatch):
    import sm_billing.contracts as contracts

    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    monkeypatch.setattr(contracts, "worker_subject_mode", lambda: "user")
    assert subject.worker_mode() == "user"


def test_worker_mode_propagates_settings_errors(monkeypatch):
    import sm_billing.contracts as contracts

    def down():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    monkeypatch.setattr(contracts, "worker_subject_mode", down)
    with pytest.raises(RuntimeError):
        subject.worker_mode()


def test_app_mode_reads_app_state(monkeypatch):
    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    app = SimpleNamespace(state=SimpleNamespace(billing_subject_mode="user"))
    assert subject.app_mode(app) == "user"


def test_runtime_billing_mode_defaults_to_tenant(pipe):
    assert pipe.runtime.billing_mode() == "tenant"


def test_runtime_mode_reads_the_bound_runtime(pipe):
    import dataclasses

    from sm_images.pipeline.runtime import bind_runtime

    with bind_runtime(dataclasses.replace(pipe.runtime, subject_mode=lambda: "user")):
        assert subject.runtime_mode() == "user"


def _unbound(monkeypatch):
    from sm_images.pipeline import runtime

    monkeypatch.setattr(runtime, "current_runtime", lambda: None)


def test_runtime_mode_unbound_reads_the_stored_mode(monkeypatch):
    """Ingest outside a bound runtime (a CLI, a bare worker) must not bill the
    tenant in ``user`` mode: it reads billing's stored setting."""
    from sm_billing import contracts

    _unbound(monkeypatch)
    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    monkeypatch.setattr(contracts, "worker_subject_mode", lambda: "user")
    assert subject.runtime_mode() == "user"


def test_runtime_mode_unbound_without_billing_is_tenant(monkeypatch):
    from sm_billing import contracts

    def boom():
        raise AssertionError("billing is not installed")

    _unbound(monkeypatch)
    monkeypatch.setattr(contracts, "worker_subject_mode", boom)
    assert subject.runtime_mode() == "tenant"


def test_worker_runtime_wires_worker_mode(monkeypatch):
    from sm_images.ingest.imports import log_redact
    from sm_images.pipeline import extensions

    monkeypatch.setattr(log_redact, "install", lambda: None)
    monkeypatch.setattr(extensions, "load_extensions", lambda: None)
    monkeypatch.setattr(wr, "worker_session_factory", lambda: object())
    assert wr.worker_runtime().subject_mode is subject.worker_mode
