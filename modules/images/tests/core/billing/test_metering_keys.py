"""Every idempotency key the module hands billing fits billing's limit.

A prompt step's id is ``prompt:<uuid>``; with a 32-character tenant, a uuid
image and a uuid lease token the readable composite was ~135 characters, past
billing's ``KEY_MAX`` (121), so every prompt run failed with ``ValueError``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sm_billing.metering.validate import KEY_MAX, check_text
from sm_images.core import billing
from sm_images.pipeline.ai import group_run, runner

TENANT = "t" * 32  # billing's TENANT_MAX
STEP = f"prompt:{uuid.uuid4()}"


def _ctx(tenant: str = TENANT, image: uuid.UUID | None = None, step: str = STEP):
    return SimpleNamespace(
        tenant_id=tenant,
        image=SimpleNamespace(id=image or uuid.uuid4()),
        step=SimpleNamespace(id=step),
    )


def _fits(key: str) -> None:
    check_text("idempotency_key", key, KEY_MAX)  # billing's own check
    assert not key.endswith(":refund") and not key.startswith("adjust:")


def test_image_prompt_key_fits_at_max_length() -> None:
    key = runner.metering_key(_ctx(), 2**31 - 1, uuid.uuid4())
    _fits(key)
    assert key.startswith("images:prompt:")


def test_image_key_is_deterministic_and_distinct() -> None:
    image, token = uuid.uuid4(), uuid.uuid4()
    ctx = _ctx(image=image)
    assert runner.metering_key(ctx, 3, token) == runner.metering_key(_ctx(image=image), 3, token)
    others = {
        runner.metering_key(ctx, 4, token),
        runner.metering_key(ctx, 3, uuid.uuid4()),
        runner.metering_key(_ctx(image=image, step="classify"), 3, token),
        runner.metering_key(_ctx(tenant="other", image=image), 3, token),
        runner.metering_key(_ctx(), 3, token),
    }
    assert runner.metering_key(ctx, 3, token) not in others
    assert len(others) == 5


def test_classify_key_fits() -> None:
    _fits(runner.metering_key(_ctx(step="classify"), 1, uuid.uuid4()))


def test_group_prompt_key_fits_at_max_length() -> None:
    job = SimpleNamespace(prompt_id=uuid.uuid4(), revision=2**31 - 1)
    key = group_run.metering_key(TENANT, job, uuid.uuid4(), uuid.uuid4())
    _fits(key)
    assert key.startswith("images:group:")


def test_group_key_is_deterministic_and_distinct() -> None:
    job = SimpleNamespace(prompt_id=uuid.uuid4(), revision=1)
    group, token = uuid.uuid4(), uuid.uuid4()
    key = group_run.metering_key(TENANT, job, group, token)
    assert key == group_run.metering_key(TENANT, job, group, token)
    assert key != group_run.metering_key(TENANT, job, group, uuid.uuid4())
    newer = SimpleNamespace(prompt_id=job.prompt_id, revision=2)
    assert key != group_run.metering_key(TENANT, newer, group, token)


def test_module_limit_matches_billing() -> None:
    from sm_images.core.billing import metering_keys

    assert metering_keys.KEY_MAX == KEY_MAX


def test_storage_hold_keys_fit_at_max_length() -> None:
    image = uuid.uuid4()
    for attempt in (uuid.uuid4().hex, f"swap-{uuid.uuid4().hex}", f"0-{uuid.uuid4().hex}"):
        _fits(billing.hold_key(image, attempt))
