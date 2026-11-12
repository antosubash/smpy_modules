"""Who a test send may go to, and what a refused recipient costs (#348)."""

from __future__ import annotations

import contextlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from simple_module_core.user_directory import DirectoryUser, set_user_directory
from sm_newsletter.campaigns import test_send
from sm_newsletter.campaigns.test_recipients import allowed_recipients
from sm_newsletter.core import constants
from sm_newsletter.core.suppression.hashing import email_hash, normalise_email
from sm_newsletter.core.suppression.store import suppress
from sm_newsletter.core.tenancy import TenancyMode, tenant_scope
from sm_newsletter.sending.transport import console

from tests.support.sending import NOW, T, attempt_rows, make_app, send, used

A, B, C = "a@example.org", "b@example.org", "c@example.org"


async def _suppress(state, email: str, reason: str, list_type_key: str = "") -> None:
    async with state.session_factory() as db:
        with tenant_scope(T):
            await suppress(
                db,
                tenant_id=T,
                email=email,
                reason=reason,
                source="admin",
                list_type_key=list_type_key,
                now=NOW,
            )
            await db.commit()


class TestSendTestRefusals:
    async def test_an_address_not_vouched_for_is_not_sent(self, built):
        app, state, cid = built
        results = await send(app, state, cid, [A, B], allowed={A})
        assert [(r.recipient, r.outcome, r.code) for r in results] == [
            (A, "accepted", "smtp_250"),
            (B, test_send.NOT_ALLOWED, None),
        ]
        assert [r.recipient for r in await attempt_rows(state)] == [A]
        assert [m.to for m in console.captured(T)] == [A]

    @pytest.mark.parametrize(
        ("reason", "key"),
        [(constants.REASON_COMPLAINT, ""), (constants.REASON_UNSUBSCRIBED, "other-list")],
    )
    async def test_a_complaint_or_any_opt_out_is_suppressed(self, built, reason, key):
        app, state, cid = built
        await _suppress(state, " B@Example.org ", reason, key)  # normalised like the table
        results = await send(app, state, cid, [A, B])
        assert [(r.recipient, r.outcome, r.code) for r in results] == [
            (A, "accepted", "smtp_250"),
            (B, test_send.SUPPRESSED, None),  # which kind is not said
        ]
        assert [r.recipient for r in await attempt_rows(state)] == [A]

    async def test_a_bounce_does_not_refuse_a_test(self, built):
        app, state, cid = built
        await _suppress(state, A, constants.REASON_HARD_BOUNCE)
        [result] = await send(app, state, cid, [A])
        assert result.outcome == "accepted"

    async def test_only_what_is_sent_is_budgeted(self):
        app, state, cid = await make_app(daily_limit=2)
        try:
            await used(state, at=NOW - timedelta(hours=1), count=1)  # one slot left
            await _suppress(state, B, constants.REASON_COMPLAINT)
            results = await send(app, state, cid, [A, B, C], allowed={A, B})
            assert [r.outcome for r in results] == [
                "accepted",
                test_send.SUPPRESSED,
                test_send.NOT_ALLOWED,
            ]
        finally:
            await state.engine.dispose()

    async def test_nothing_to_send_takes_no_lock_and_no_budget(self, built, monkeypatch):
        app, state, cid = built
        app.state.sm_newsletter.settings.daily_limit = 1
        await used(state, at=NOW, count=1)  # the budget is spent
        await _suppress(state, A, constants.REASON_COMPLAINT)

        @contextlib.asynccontextmanager
        async def no_lock(*args, **kwargs):
            raise AssertionError("the dispatch lock was taken")
            yield

        monkeypatch.setattr(test_send, "dispatch_lock", no_lock)
        results = await send(app, state, cid, [A, B], allowed={A})
        assert [r.outcome for r in results] == [test_send.SUPPRESSED, test_send.NOT_ALLOWED]
        assert len(await attempt_rows(state)) == 1  # only the seeded one


class _Directory:
    def __init__(self, *users: DirectoryUser) -> None:
        self.users = users

    async def search(self, db, term, *, limit):
        return [u for u in self.users if term in u.email.lower()][:limit]


def _request(app, *, email: str = "me@example.org", tenant: str | None = None):
    return SimpleNamespace(
        app=app,
        scope={},
        state=SimpleNamespace(user=SimpleNamespace(email=email), tenant_id=tenant),
    )


async def _allowed(app, state, recipients, **request):
    async with state.session_factory() as db:
        settings = app.state.sm_newsletter.settings
        return await allowed_recipients(
            _request(app, **request),
            db,
            tenant_id=request.get("tenant") or T,
            recipients=recipients,
            settings=settings,
        )


class TestAllowedRecipients:
    async def test_the_caller_and_the_allow_list(self, built):
        app, state, _ = built
        app.state.sm_newsletter.settings.test_send_extra_recipients = ["review@example.org"]
        got = await _allowed(app, state, ["me@example.org", "review@example.org", A])
        assert got == {"me@example.org", "review@example.org"}

    async def test_no_directory_vouches_for_nobody_else(self, built):
        app, state, _ = built
        assert await _allowed(app, state, [A]) == frozenset()

    async def test_single_tenant_active_users_by_exact_address(self, built):
        app, state, _ = built
        set_user_directory(
            app,
            _Directory(
                DirectoryUser(id="1", email="A@Example.org"),
                DirectoryUser(id="2", email=B, is_active=False),
                DirectoryUser(id="3", email="xc@example.org"),  # contains C's text
            ),
        )
        assert await _allowed(app, state, [A, B, C]) == {A}

    async def test_multi_tenant_needs_membership_of_the_bound_tenant(self, built):
        app, state, _ = built
        app.state.sm_newsletter.tenancy = TenancyMode.MULTI
        set_user_directory(
            app, _Directory(DirectoryUser(id="1", email=A), DirectoryUser(id="2", email=B))
        )
        seen = {}

        async def members(db, tenant_id, user_ids):
            seen["tenant"] = tenant_id
            return [u for u in user_ids if u == "1"]

        app.state.tenant_members = members
        assert await _allowed(app, state, [A, B], tenant="org-1") == {A}
        assert seen == {"tenant": "org-1"}

    async def test_multi_tenant_without_a_membership_store_fails_closed(self, built):
        app, state, _ = built
        app.state.sm_newsletter.tenancy = TenancyMode.MULTI
        set_user_directory(app, _Directory(DirectoryUser(id="1", email=A)))
        assert await _allowed(app, state, [A], tenant="org-1") == frozenset()


FULLWIDTH_E = "\uff45"  # the address parser folds it into "e"; the store keeps it


class TestCanonicalForm:
    """One canonical form on both sides (#348): a suppression written in one
    spelling blocks a test to the other."""

    @pytest.mark.parametrize(
        ("stored", "sent"),
        [
            (f"b@{FULLWIDTH_E}xample.org", B),  # written fullwidth, sent ASCII
            (B, f"b@{FULLWIDTH_E}xample.org"),  # written ASCII, sent fullwidth
            ("b@xn--bcher-kva.de", "b@b\u00fccher.de"),  # punycode vs Unicode domain
        ],
    )
    async def test_a_suppression_blocks_every_spelling(self, built, stored, sent):
        app, state, cid = built
        await _suppress(state, stored, constants.REASON_COMPLAINT)
        [result] = await send(app, state, cid, [sent])
        assert result.outcome == test_send.SUPPRESSED
        assert await attempt_rows(state) == []

    def test_ascii_keys_are_unchanged(self):
        # sha256("a@example.org"): the key every pre-#348 ASCII row was written with.
        expected = "e16bfe08be114c7b3737aa01ce504ebcb5d13fc44897c38c6cac63ddc7151463"
        assert email_hash(" A@Example.ORG ") == expected
        assert normalise_email("Stra\u00dfe@X.org") == "stra\u00dfe@x.org"  # lower(), not casefold

    async def test_an_allow_list_entry_matches_in_either_form(self, built):
        app, state, _ = built
        app.state.sm_newsletter.settings.test_send_extra_recipients = [
            f"review@{FULLWIDTH_E}xample.org"
        ]
        assert await _allowed(app, state, ["review@example.org"]) == {"review@example.org"}
