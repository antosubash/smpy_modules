"""Every closed door of the submission routes is one 404 (#101): an unknown
key, a type without the config or switched off, a newsletter list that is off,
and the master switch. Split from ``test_public_submissions_submit``."""

from __future__ import annotations

from tests.app_harness import ADMIN, roles
from tests.submissions_http import SUBMISSIONS, configure, contact_type, send


async def test_every_closed_door_is_the_same_404(site):
    await contact_type(site)
    await contact_type(site, "closed", enabled=False)
    plain = await site.post(
        "/api/records/types",
        json={"key": "plain", "label": "P", "fields": []},
        headers=roles(ADMIN),
    )
    assert plain.status_code == 201, plain.text
    news = await site.post(
        "/api/records/types",
        json={
            "key": "news",
            "label": "N",
            "fields": [],
            "public_submissions": {"kind": "subscription", "enabled": False},
        },
        headers=roles(ADMIN),
    )
    assert news.status_code == 201, news.text
    unknown = await site.get(f"{SUBMISSIONS}/nosuch")
    assert unknown.status_code == 404
    for key in ("closed", "plain", "news"):
        resp = await site.get(f"{SUBMISSIONS}/{key}")
        assert (resp.status_code, resp.json()) == (404, unknown.json()), key
        posted = await send(site, key, token="x")
        assert posted.status_code in (400, 404), key
    configure(site, public_submissions_enabled=False)
    resp = await site.get(f"{SUBMISSIONS}/contact")
    assert (resp.status_code, resp.json()) == (404, unknown.json())
    assert (await send(site, token="x")).status_code == 404
