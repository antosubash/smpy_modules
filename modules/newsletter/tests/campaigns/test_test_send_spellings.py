"""Spellings in the test send: one canonical form, and legacy-keyed rows (#348)."""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import test_send
from sm_newsletter.core import constants
from sm_newsletter.core.suppression.hashing import legacy_hash
from sm_newsletter.core.suppression.store import suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression

from tests.support.sending import FULLWIDTH_E, NOW, T, attempt_rows, send, suppress_in

B = "b@example.org"
RAW = f"b@{FULLWIDTH_E}xample.org"


async def _legacy_row(state, email: str) -> None:
    """A row as a pre-#348 build wrote it: keyed by sha256(strip().lower())."""
    async with state.session_factory() as db:
        with tenant_scope(T):
            db.add(
                Suppression(
                    tenant_id=T,
                    email_hash=legacy_hash(email),
                    reason=constants.REASON_COMPLAINT,
                    source="admin",
                    created_at=NOW,
                )
            )
            await finalize_session(db)


@pytest.mark.parametrize(
    ("stored", "sent"),
    [
        (RAW, B),  # written fullwidth, sent ASCII
        (B, RAW),  # written ASCII, sent fullwidth
        ("b@xn--fa-hia.de", "b@fa\u00df.de"),  # punycode vs Unicode domain
    ],
)
async def test_a_suppression_blocks_every_spelling(built, stored, sent):
    app, state, cid = built
    await suppress_in(state, stored, constants.REASON_COMPLAINT)
    [result] = await send(app, state, cid, [sent])
    assert result.outcome == test_send.SUPPRESSED
    assert await attempt_rows(state) == []


async def test_a_legacy_keyed_row_still_blocks(built):
    # Written by an earlier build under the raw spelling's old key; the request
    # carries that spelling, parsed to the ASCII form (fail closed).
    app, state, cid = built
    await _legacy_row(state, RAW)
    [result] = await send(app, state, cid, [B], submitted={B: [RAW]})
    assert result.outcome == test_send.SUPPRESSED
    async with state.session_factory() as db:  # freeze and the browser read this way
        assert await suppressed(db, tenant_id=T, emails=[RAW]) == {B}
