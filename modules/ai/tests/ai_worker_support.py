"""Helpers shared by the worker-path suites (``test_worker_settings*``).

Uniquely named for the reason ``ai_test_stubs`` is; the fixtures that use
them live in ``conftest.py``.
"""

from __future__ import annotations

import threading

from pydantic_ai.models.anthropic import AnthropicModel
from settings.models import Setting
from sm_ai import crypto
from sm_ai.contracts import resolve_model
from sqlmodel import Session, select

DB_SECRET = "generated-and-stored-by-the-web-host"


def put(engine, key: str, value: str, value_type: str = "string") -> None:
    with Session(engine) as s:
        row = s.exec(select(Setting).where(Setting.key == key)).first()
        if row is None:
            row = Setting(key=key, value=value, value_type=value_type)
        row.value = value
        s.add(row)
        s.commit()


def encrypt_as_web_host(plain: str) -> str:
    crypto.set_secret_provider(lambda: DB_SECRET)
    try:
        return crypto.encrypt_value(plain)
    finally:
        crypto._secret_provider = None


def run_task(call=resolve_model):
    """What a ``@shared_task`` body does: resolve, on a worker thread."""
    out: dict = {}

    def run():
        try:
            out["model"] = call()
        except BaseException as exc:  # surfaced to the test below
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "error" in out:
        raise out["error"]
    return out["model"]


def key_of(model: AnthropicModel) -> str:
    return model.client.api_key
