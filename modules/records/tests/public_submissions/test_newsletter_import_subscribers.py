"""``import_subscribers`` and ``opted_out_anywhere`` (newsletter PR 7, task 2).

The import never confirms a pending signup, never resubscribes anyone who
left, writes into an existing subscriber only through a validating write and
publishes nothing. Rows against an existing record are in
``test_newsletter_import_existing.py``; the two-transaction tests are in
``test_newsletter_import_races.py`` (Postgres only).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records.contracts.newsletter import iter_subscribers
from sm_records.contracts.newsletter_import import (
    ImportRow,
    SubscriberFilterError,
    import_subscribers,
    opted_out_anywhere,
)
from sm_records.core import events
from sm_records.core.locales import default
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions.campaign_reads import moment
from sm_records.records.services import types as type_service

from tests.support.app_harness import field
from tests.support.newsletter_contract import TENANT, session, unbound
from tests.support.newsletter_import import (
    KEY,
    NOW,
    SETTINGS,
    Spy,
    T,
    make_list,
    outcomes,
    run,
    seed,
    stored,
)

ADA = "ada@example.org"


def row(email: str, status: str = "confirmed", **kw) -> ImportRow:
    return ImportRow(email=email, status=status, **kw)


async def _hit(site, email: str):
    async with session(site) as db:
        hits, _ = await iter_subscribers(db, tenant_id=TENANT, type_key=KEY, status="confirmed")
    return next(h for h in hits if h.email == email)


async def test_creates_confirmed_with_consent_snapshot(site):
    await make_list(site)
    rows = [row(" Ada@Example.org ", fields={"first_name": "Ada"}, tags=["a"], confirmed_at=T)]
    [result] = await run(site, rows)
    assert (result.email, result.outcome, result.dropped) == (ADA, "created", [])
    hit = await _hit(site, ADA)
    assert (hit.tags, hit.first_name, hit.confirmed_at) == (["a"], "Ada", T)
    data = (await stored(site, ADA)).data
    assert data["sm_consent_text"] == "Imported from Mailchimp on 2026-11-05"
    assert moment(data["sm_consent_at"]) == NOW
    assert data["sm_locale"] == default(SETTINGS)
    assert len(data["sm_nonce"]) == 32
    assert data.get("sm_consent_ip_hash") is None and data.get("sm_source_page") is None


async def test_confirmed_at_falls_back_and_is_clamped(site):
    await make_list(site)
    later = NOW + timedelta(days=3)
    rows = [
        row("a@x.org"),
        row("b@x.org", consent_at=T),
        row("c@x.org", confirmed_at=later, consent_at=later),
    ]
    assert set(outcomes(await run(site, rows)).values()) == {"created"}
    assert (await _hit(site, "a@x.org")).confirmed_at == NOW
    assert (await _hit(site, "b@x.org")).confirmed_at == T
    assert moment((await stored(site, "b@x.org")).data["sm_consent_at"]) == T
    assert (await _hit(site, "c@x.org")).confirmed_at == NOW


async def test_creates_unsubscribed_record_without_values(site):
    await make_list(site)
    rows = [row(ADA, "unsubscribed", fields={"first_name": "Ada"}, tags=["a"], unsubscribed_at=T)]
    assert outcomes(await run(site, rows)) == {ADA: "created_unsubscribed"}
    data = (await stored(site, ADA)).data
    assert data["sm_status"] == "unsubscribed"
    assert moment(data["sm_unsubscribed_at"]) == T
    assert data.get("first_name") is None and not data.get("tags")
    assert data.get("sm_consent_text") is None and data.get("sm_consent_at") is None


async def test_opted_out_anywhere(site):
    await make_list(site)
    await make_list(site, key="monthly")
    await make_list(site, tenant="other")
    await seed(site, ADA, "unsubscribed", trashed=True)
    await seed(site, "bob@example.org", "unsubscribed", key="monthly")
    await seed(site, "cy@example.org")
    await seed(site, "dee@example.org", "pending")
    await seed(site, "eve@example.org", "unsubscribed", tenant="other")
    asked = [" ADA@example.org", "bob@example.org", "cy@example.org", "dee@example.org"]
    async with session(site) as db:
        with unbound():
            found = await opted_out_anywhere(
                db, tenant_id=TENANT, emails=[*asked, "eve@example.org", "x@y.org"]
            )
            theirs = await opted_out_anywhere(db, tenant_id="other", emails=asked)
            with pytest.raises(ValueError):
                await opted_out_anywhere(
                    db, tenant_id=TENANT, emails=[f"{i}@x.org" for i in range(501)]
                )
    assert found == {ADA, "bob@example.org"}
    assert theirs == set()


async def test_import_publishes_no_events(site):
    await make_list(site)
    await seed(site, "upd@x.org")
    await seed(site, "same@x.org", data={"tags": ["a"]})
    await seed(site, "leave@x.org", confirmed_at=T)
    await seed(site, "stay@x.org", confirmed_at=NOW)
    await seed(site, "pend@x.org", "pending")
    await seed(site, "gone@x.org", "unsubscribed")
    await seed(site, "bin@x.org", trashed=True)
    rows = [
        row("new@x.org"),
        row("newun@x.org", "unsubscribed"),
        row("upd@x.org", tags=["a"]),
        row("same@x.org", tags=["a"]),
        row("leave@x.org", "unsubscribed", unsubscribed_at=T + timedelta(days=1)),
        row("stay@x.org", "unsubscribed", unsubscribed_at=T),
        row("pend@x.org"),
        row("gone@x.org"),
        row("bin@x.org"),
        row("not an address"),
    ]
    spy = Spy()
    results = await run(site, rows, spy=spy)
    assert [r.outcome for r in results] == [
        "created",
        "created_unsubscribed",
        "updated",
        "unchanged",
        "unsubscribed",
        "kept_confirmed",
        "kept_pending",
        "kept_unsubscribed",
        "trashed",
        "invalid",
    ]
    assert spy.seen == []


async def test_invalid_value_is_dropped_not_fatal(site):
    await make_list(site)
    rows = [
        row(ADA, fields={"team": "nope", "first_name": "Ada"}),
        row("b@x.org", fields={"team": "X"}),
    ]
    results = await run(site, rows)
    assert [(r.outcome, r.dropped) for r in results] == [("created", ["team"]), ("created", [])]
    assert (await _hit(site, ADA)).first_name == "Ada"
    assert (await stored(site, "b@x.org")).data["team"] == "x"  # a label maps to its value


async def test_unknown_tag_is_dropped(site):
    await make_list(site)
    [result] = await run(site, [row(ADA, tags=["a", "zzz"])])
    assert (result.outcome, result.dropped) == ("created", ["tags"])
    assert (await _hit(site, ADA)).tags == []


async def test_batch_arguments_refused(site):
    await make_list(site)
    naive = datetime(2026, 1, 1)
    bad = [
        [row(f"{i}@x.org") for i in range(501)],
        [row("Ada@X.org"), row("ada@x.org ")],
        [row(ADA, confirmed_at=naive)],
        [ImportRow.model_construct(email=ADA, status="cleaned", fields={}, tags=[])],
    ]
    for rows in bad:
        with pytest.raises(ValueError):
            await run(site, rows)
    with pytest.raises(ValueError):
        await run(site, [row(ADA)], now=naive)
    with pytest.raises(LookupError):
        await run(site, [row(ADA)], key="nope")
    async with session(site) as db:
        with tenant_scope(TENANT):
            await type_service.create_type(
                db,
                key="contact",
                label="Contact",
                fields_raw=[field("name")],
                public_submissions={"kind": "form"},
                settings=SETTINGS,
            )
            await events.commit(db)
    with pytest.raises(SubscriberFilterError):
        await run(site, [row(ADA)], key="contact")
    async with session(site) as db:
        with unbound():
            hits, _ = await iter_subscribers(db, tenant_id=TENANT, type_key=KEY)
    assert hits == []


async def test_import_pins_the_tenant(site):
    await make_list(site)
    await make_list(site, tenant="other")
    await seed(site, ADA, tenant="other")
    theirs = await stored(site, ADA, tenant="other")
    rows = [row(ADA, fields={"first_name": "Ada"}), row("bob@example.org")]
    assert set(outcomes(await run(site, rows)).values()) == {"created"}
    after = await stored(site, ADA, tenant="other")
    assert (after.version, after.data) == (theirs.version, theirs.data)
    assert (await _hit(site, ADA)).first_name == "Ada"


async def test_import_runs_under_its_own_tenant_only(site):
    await make_list(site)
    with unbound(), tenant_scope("other"), pytest.raises(TenantIsolationError):
        async with session(site) as db:
            await import_subscribers(
                db, tenant_id=TENANT, type_key=KEY, rows=[row(ADA)], settings=SETTINGS, now=NOW
            )


async def test_conflict_redecides_once(site, monkeypatch):
    """A ``Conflict`` (a concurrent signup claimed the address) re-reads the
    address and decides again; a second one is ``invalid``."""
    from sm_records.public_submissions import campaign_import_rows
    from sm_records.records.services.errors import Conflict

    await make_list(site)
    real = campaign_import_rows.record_service.create_record
    calls: list[str] = []

    async def racing(db, rtype, **kw):
        calls.append(kw["system"]["sm_email"])
        if len(calls) == 1 or kw["system"]["sm_email"] == "bob@example.org":
            raise Conflict("'sm_email' must be unique")
        return await real(db, rtype, **kw)

    monkeypatch.setattr(campaign_import_rows.record_service, "create_record", racing)
    results = await run(site, [row(ADA), row("bob@example.org")])
    assert [r.outcome for r in results] == ["created", "invalid"]
    assert calls == [ADA, ADA, "bob@example.org", "bob@example.org"]
