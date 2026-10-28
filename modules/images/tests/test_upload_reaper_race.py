"""The reaper's takeover re-checks expiry atomically (Phase 2 round 3, Codex P2).

The candidate SELECT and the takeover UPDATE are separate statements. A lease
renewed (or an open session extended) between them must make the takeover
miss: the UPDATE's own WHERE carries the expiry check, not just status + token.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import constants
from sm_images.ingest import upload_reaper
from sm_images.models import UploadStatus

from tests.test_upload_lease import _row, _update
from tests.test_upload_reaper import _one_part_in, _parts_exist, _reap
from tests.upload_support import make_collection


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


def _between_select_and_takeover(monkeypatch, uploads, ticket, **values):
    """Run ``_update(**values)`` after the candidates are read, before the takeover."""
    real = upload_reaper._take_over

    async def renew_first(*args):
        await _update(uploads, ticket, **values)
        return await real(*args)

    monkeypatch.setattr(upload_reaper, "_take_over", renew_first)


async def test_a_lease_renewed_after_selection_is_not_taken_over(uploads, monkeypatch):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    token = uuid.uuid4()
    now = datetime.now(UTC)
    await _update(
        uploads,
        ticket,
        status=UploadStatus.COMPLETING,
        claim_token=token,
        lease_expires_at=now - timedelta(seconds=1),
    )
    _between_select_and_takeover(
        monkeypatch, uploads, ticket, lease_expires_at=now + timedelta(minutes=15)
    )

    assert await _reap(uploads, now) == 0
    row = await _row(uploads, ticket)
    assert row.status is UploadStatus.COMPLETING and row.claim_token == token
    assert _parts_exist(uploads, ticket)


async def test_an_open_session_extended_after_selection_is_not_taken_over(uploads, monkeypatch):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    now = datetime.now(UTC)
    await _update(uploads, ticket, expires_at=now - timedelta(seconds=1))
    _between_select_and_takeover(monkeypatch, uploads, ticket, expires_at=now + timedelta(hours=1))

    assert await _reap(uploads, now) == 0
    assert (await _row(uploads, ticket)).status is UploadStatus.OPEN
    assert _parts_exist(uploads, ticket)
