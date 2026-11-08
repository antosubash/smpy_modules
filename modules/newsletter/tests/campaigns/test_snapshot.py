"""``snapshot_render``: the stored render of a campaign about to be scheduled."""

from __future__ import annotations

import dataclasses

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import snapshot
from sm_newsletter.core.errors import NewsletterError
from sm_newsletter.models import Campaign, CampaignRender, Link
from sqlalchemy import func, select

from tests.support.campaign_world import render_row, set_columns
from tests.support.sending import NOW, T


async def _snapshot(app, state, cid):
    async with state.session_factory() as db:
        campaign = await db.get(Campaign, cid)
        row = await snapshot.snapshot_render(app, db, tenant_id=T, campaign=campaign, now=NOW)
        await finalize_session(db)
        return row


async def test_snapshot_replaces_previous(built):
    app, state, cid = built
    await _snapshot(app, state, cid)
    await set_columns(state, T, cid, subject="Second {{first_name}}")
    row = await _snapshot(app, state, cid)
    assert row.subject == "Second {{first_name}}"
    async with state.session_factory() as db:
        count = await db.scalar(select(func.count()).select_from(CampaignRender))
    assert count == 1
    stored = await render_row(state, T, cid)
    assert stored.subject == "Second {{first_name}}"
    assert "[TEST]" not in stored.subject
    async with state.session_factory() as db:
        await snapshot.drop_render(db, tenant_id=T, campaign_id=cid)
        await finalize_session(db)
    assert await render_row(state, T, cid) is None


async def test_snapshot_uses_campaign_from_name_and_reply_to(built):
    app, state, cid = built
    app.state.sm_newsletter.settings.reply_to = "desk@example.org"
    row = await _snapshot(app, state, cid)
    assert (row.sender, row.reply_to) == ("News <news@example.org>", "desk@example.org")
    await set_columns(state, T, cid, from_name="Spring Team", reply_to="spring@example.org")
    row = await _snapshot(app, state, cid)
    assert (row.sender, row.reply_to) == ("Spring Team <news@example.org>", "spring@example.org")


async def test_snapshot_rejects_header_injection_in_settings(built):
    app, state, cid = built
    app.state.sm_newsletter.settings.from_name = "News\x07Bcc"
    with pytest.raises(NewsletterError) as err:
        await _snapshot(app, state, cid)
    assert err.value.status == 422
    assert "Bcc" not in err.value.detail
    assert await render_row(state, T, cid) is None


def _links_body():
    return [
        {"type": "Button", "props": {"id": "b", "label": "Go", "href": "https://e.org/a"}},
        {
            "type": "Image",
            "props": {"id": "i", "src": "/media/x.png", "href": "https://e.org/b"},
        },
    ]


async def _links(state, cid):
    async with state.session_factory() as db:
        stmt = select(Link).where(Link.tenant_id == T, Link.campaign_id == cid)
        return sorted((await db.execute(stmt)).scalars(), key=lambda link: link.position)


async def test_snapshot_stores_links_and_placeholders(built):
    app, state, cid = built
    await set_columns(state, T, cid, body=_links_body())
    await _snapshot(app, state, cid)
    links = await _links(state, cid)
    assert [(x.position, x.url, x.tenant_id) for x in links] == [
        (1, "https://e.org/a", T),
        (2, "https://e.org/b", T),
    ]
    stored = await render_row(state, T, cid)
    assert "{{link:1}}" in stored.html and "{{link:2}}" in stored.html
    assert stored.html.count("{{open_pixel}}") == 1
    assert "https://e.org/a" not in stored.html
    assert "https://e.org/a" in stored.text  # T4: the text part is not rewritten


async def test_snapshot_replaces_links(built):
    app, state, cid = built
    await set_columns(state, T, cid, body=_links_body())
    await _snapshot(app, state, cid)
    await set_columns(state, T, cid, body=_links_body()[:1])
    await _snapshot(app, state, cid)
    assert [x.url for x in await _links(state, cid)] == ["https://e.org/a"]


async def test_drop_render_drops_links(built):
    app, state, cid = built
    await set_columns(state, T, cid, body=_links_body())
    await _snapshot(app, state, cid)
    async with state.session_factory() as db:
        await snapshot.drop_render(db, tenant_id=T, campaign_id=cid)
        await finalize_session(db)
    assert await _links(state, cid) == []
    assert await render_row(state, T, cid) is None


async def test_placeholder_in_content_is_invalid_campaign_422(built, monkeypatch):
    app, state, cid = built
    real = snapshot.render

    def spelled(*args, **kwargs):
        return dataclasses.replace(real(*args, **kwargs), html="<p>{{open_pixel}}</p>")

    monkeypatch.setattr(snapshot, "render", spelled)
    with pytest.raises(NewsletterError) as err:
        await _snapshot(app, state, cid)
    assert (err.value.status, err.value.code) == (422, "invalid_campaign")
    assert "open_pixel" not in err.value.detail


async def test_snapshot_refuses_an_encoded_sender_past_the_column(built):
    app, state, cid = built
    await set_columns(state, T, cid, from_name="新" * 200)
    with pytest.raises(NewsletterError) as err:
        await _snapshot(app, state, cid)
    assert err.value.status == 422
    assert await render_row(state, T, cid) is None
