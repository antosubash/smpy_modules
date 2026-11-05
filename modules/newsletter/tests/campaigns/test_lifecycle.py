"""Scheduling and unscheduling: validation, the render snapshot and the freeze fence."""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.content import context
from sm_newsletter.core.errors import NewsletterError, NotFound
from sm_newsletter.models import Campaign, Link
from sqlalchemy import func, select

from tests.support.campaign_world import (
    campaign_row,
    render_row,
    seed_campaign,
    seed_sends,
    send_rows,
    set_columns,
)
from tests.support.records_seed import restrict_list
from tests.support.sending import BASE_URL, NOW, T


async def _schedule(app, state, cid, *, revision=1, scheduled_at=None, roles=()):
    async with state.session_factory() as db:
        campaign = await lifecycle.schedule(
            app,
            db,
            tenant_id=T,
            campaign_id=cid,
            roles=list(roles),
            expected_revision=revision,
            scheduled_at=scheduled_at,
            now=NOW,
        )
        await finalize_session(db)
        return campaign


async def _unschedule(state, cid, *, revision):
    async with state.session_factory() as db:
        campaign = await lifecycle.unschedule(
            db, tenant_id=T, campaign_id=cid, roles=[], expected_revision=revision
        )
        await finalize_session(db)
        return campaign


async def test_schedule_now_snapshots_and_schedules(built):
    app, state, cid = built
    campaign = await _schedule(app, state, cid)
    assert (campaign.status, campaign.revision, campaign.scheduled_at) == ("scheduled", 2, NOW)
    row = await render_row(state, T, cid)
    assert row is not None
    assert "{{unsubscribe_url}}" in row.html and "{{unsubscribe_url}}" in row.text
    assert row.subject == "Hello"
    assert row.sender == "News <news@example.org>"
    assert (row.public_base, row.content_base, row.locale, row.rendered_at) == (
        BASE_URL,
        BASE_URL,
        "en",
        NOW,
    )


async def test_schedule_later_keeps_the_time(built):
    app, state, cid = built
    later = NOW + timedelta(days=3)
    campaign = await _schedule(app, state, cid, scheduled_at=later)
    assert (campaign.status, campaign.scheduled_at) == ("scheduled", later)


async def test_schedule_stale_409_and_no_snapshot(built):
    app, state, cid = built
    with pytest.raises(NewsletterError) as err:
        await _schedule(app, state, cid, revision=7)
    assert (err.value.status, err.value.code) == (409, "stale")
    assert (await campaign_row(state, T, cid)).status == "draft"
    assert await render_row(state, T, cid) is None


async def test_schedule_not_a_draft_409(built):
    app, state, _ = built
    cid = await seed_campaign(state, T, status="sending", started_at=NOW)
    with pytest.raises(NewsletterError) as err:
        await _schedule(app, state, cid)
    assert (err.value.status, err.value.code) == (409, "not_a_draft")
    assert await render_row(state, T, cid) is None


def _settings(**values):
    def apply(app, state, cid, monkeypatch):
        for key, value in values.items():
            setattr(app.state.sm_newsletter.settings, key, value)

    return apply


def _columns(**values):
    async def apply(app, state, cid, monkeypatch):
        await set_columns(state, T, cid, **values)

    return apply


def _base(url):
    def apply(app, state, cid, monkeypatch):
        app.state.sm.settings.public_base_url = url

    return apply


def _http_content_origin(app, state, cid, monkeypatch):
    async def content_base(_app, _tenant, _public):
        return "http://acme.example.org"

    _settings(transport="smtp", smtp_host="smtp.example.org")(app, state, cid, monkeypatch)
    monkeypatch.setattr(context, "_content_base", content_base)


SMTP = {"transport": "smtp", "smtp_host": "smtp.example.org"}
REFUSALS = {
    "no_from_address": (_settings(from_address=" "), None, "sender_not_configured"),
    "no_physical_address": (_settings(physical_address=""), None, "sender_not_configured"),
    "empty_body": (_columns(body=[]), None, "empty_campaign"),
    "blank_subject": (_columns(subject="  "), None, "invalid_campaign"),
    "no_public_base_url": (_base(""), None, "public_base_url_required"),
    "in_the_past": (None, NOW - timedelta(minutes=2), "invalid_campaign"),
    "too_far_ahead": (None, NOW + timedelta(days=400), "invalid_campaign"),
    "naive_time": (None, NOW.replace(tzinfo=None), "invalid_campaign"),
    "tag_audience": (_columns(audience="tag:x"), None, "audience_unsupported"),
    "smtp_http_public_base": (_base("http://news.example.org"), None, "https_required"),
    "smtp_http_content_origin": (_http_content_origin, None, "https_required"),
    "capability_in_subject": (
        _columns(subject="Hi {{unsubscribe_url}}"),
        None,
        "invalid_campaign",
    ),
    "capability_in_preheader": (
        _columns(preheader="{{unsubscribe_url}}"),
        None,
        "invalid_campaign",
    ),
}


@pytest.mark.parametrize("case", list(REFUSALS))
async def test_schedule_refusals(built, monkeypatch, case):
    app, state, cid = built
    setup, scheduled_at, code = REFUSALS[case]
    if case.startswith("smtp_"):
        _settings(**SMTP)(app, state, cid, monkeypatch)
    if setup is not None:
        result = setup(app, state, cid, monkeypatch)
        if result is not None:
            await result
    before = await campaign_row(state, T, cid)
    with pytest.raises(NewsletterError) as err:
        await _schedule(app, state, cid, revision=before.revision, scheduled_at=scheduled_at)
    assert err.value.code == code
    assert err.value.status == 422
    if case.startswith("capability_"):
        assert err.value.detail.endswith("merge field not allowed here")
        assert "unsubscribe_url" not in err.value.detail
    after = await campaign_row(state, T, cid)
    assert (after.status, after.revision) == ("draft", before.revision)
    assert await render_row(state, T, cid) is None


async def test_console_transport_allows_http_base(built):
    app, state, cid = built
    app.state.sm.settings.public_base_url = "http://news.example.org"
    campaign = await _schedule(app, state, cid)
    assert campaign.status == "scheduled"
    row = await render_row(state, T, cid)
    assert (row.public_base, row.content_base) == ("http://news.example.org",) * 2


async def test_smtp_transport_with_https_bases_schedules(built):
    app, state, cid = built
    _settings(**SMTP)(app, state, cid, None)
    assert (await _schedule(app, state, cid)).status == "scheduled"


async def test_schedule_and_unschedule_bump_freeze_gen(built):
    app, state, cid = built
    await set_columns(state, T, cid, freeze_owner="worker-1", freeze_until=NOW)
    scheduled = await _schedule(app, state, cid)
    assert (scheduled.freeze_gen, scheduled.freeze_owner, scheduled.freeze_until) == (1, None, None)
    # An interrupted freeze left rows behind, and claimed the campaign again.
    await seed_sends(state, T, cid, ["queued", "queued", "suppressed"], freeze_gen=1)
    await set_columns(state, T, cid, freeze_owner="worker-2", freeze_until=NOW)
    draft = await _unschedule(state, cid, revision=scheduled.revision)
    assert (draft.freeze_gen, draft.freeze_owner, draft.freeze_until) == (2, None, None)
    assert await send_rows(state, T, cid) == []


async def test_schedule_restricted_list_is_404(built):
    app, state, cid = built
    await restrict_list(state, T, "news", ["editors"])
    with pytest.raises(NotFound):
        await _schedule(app, state, cid)
    assert (await campaign_row(state, T, cid)).status == "draft"
    assert (await _schedule(app, state, cid, roles=["editors"])).status == "scheduled"


async def test_unschedule_back_to_draft_drops_snapshot(built):
    app, state, cid = built
    scheduled = await _schedule(app, state, cid, scheduled_at=NOW + timedelta(hours=1))
    draft = await _unschedule(state, cid, revision=scheduled.revision)
    assert (draft.status, draft.scheduled_at, draft.revision) == ("draft", None, 3)
    assert await render_row(state, T, cid) is None
    # Scheduling again renders afresh.
    again = await _schedule(app, state, cid, revision=draft.revision)
    assert again.status == "scheduled" and await render_row(state, T, cid) is not None


async def test_unschedule_refusals(built):
    app, state, cid = built
    with pytest.raises(NewsletterError) as err:
        await _unschedule(state, cid, revision=1)  # still a draft
    assert (err.value.status, err.value.code) == (409, "invalid_transition")
    scheduled = await _schedule(app, state, cid)
    with pytest.raises(NewsletterError) as err:
        await _unschedule(state, cid, revision=scheduled.revision - 1)
    assert (err.value.status, err.value.code) == (409, "stale")
    assert await render_row(state, T, cid) is not None


async def test_schedule_replaces_a_leftover_render(built):
    """A render row left by an earlier schedule never blocks the next one."""
    app, state, cid = built
    await _schedule(app, state, cid)
    async with state.session_factory() as db:
        campaign = await db.get(Campaign, cid)
        campaign.status = "draft"  # around the API: the row stays
        await finalize_session(db)
    await set_columns(state, T, cid, subject="Second")
    current = await campaign_row(state, T, cid)
    await _schedule(app, state, cid, revision=current.revision)
    assert (await render_row(state, T, cid)).subject == "Second"


_LINKED = [{"type": "Button", "props": {"id": "b", "label": "Go", "href": "https://e.org/a"}}]


async def _link_count(state):
    async with state.session_factory() as db:
        return await db.scalar(select(func.count()).select_from(Link))


async def test_unschedule_drops_links(built):
    app, state, cid = built
    await set_columns(state, T, cid, body=_LINKED)
    scheduled = await _schedule(app, state, cid)
    assert await _link_count(state) == 1
    await _unschedule(state, cid, revision=scheduled.revision)
    assert await _link_count(state) == 0


async def test_schedule_writes_links_in_same_transaction(built, monkeypatch):
    app, state, cid = built
    await set_columns(state, T, cid, body=_LINKED)
    _settings(**SMTP)(app, state, cid, monkeypatch)
    _base("http://news.example.org")(app, state, cid, monkeypatch)
    before = await campaign_row(state, T, cid)
    with pytest.raises(NewsletterError) as err:  # refused after the snapshot was built
        await _schedule(app, state, cid, revision=before.revision)
    assert err.value.code == "https_required"
    assert await _link_count(state) == 0
    assert await render_row(state, T, cid) is None
