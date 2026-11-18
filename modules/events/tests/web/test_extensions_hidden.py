"""A source decides how much of its settings a manager may see, and gets them back on save."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from pydantic import BaseModel
from sm_events.calendar.plugins import registry
from sm_events.contracts.extensions import (
    RestoredSettings,
    SettingsProblem,
    SettingsView,
    SourceSettingsError,
)
from sqlalchemy import select

from tests.support.calendars import BASE, OWNER, make
from tests.support.events_http import run
from tests.support.sources import FakeSource, install

SECRET = "classified-project-x"


class Model(BaseModel):
    items: list[dict[str, Any]] = []


class Redacting(FakeSource):
    """Hides every item marked ``secret`` behind a placeholder, and puts it back on save."""

    settings_model = Model

    def __init__(self, ident="acme:red", **kw):
        super().__init__(ident, settings_model=Model, **kw)
        self.restored: list[Any] = []
        self.checked_preserved: list[Any] = []

    async def view_settings(self, sctx, settings):
        shown = [
            {"hidden": True, "token": f"h{i}"} if item.get("secret") else item
            for i, item in enumerate(settings.get("items", []))
        ]
        problems = (SettingsProblem(("items", 0, "name"), "bad_name", "Fix it"),)
        return SettingsView({**settings, "items": shown}, problems)

    async def restore_settings(self, sctx, submitted, stored):
        old = stored.get("items", [])
        out, kept = [], []
        for position, item in enumerate(submitted.get("items", [])):
            if item.get("hidden"):
                index = int(str(item.get("token", "x"))[1:] or -1)
                if not (0 <= index < len(old) and old[index].get("secret")):
                    raise SourceSettingsError(("items", position), "Unknown", "unknown")
                out.append(old[index])
                kept.append(("items", position))
            else:
                out.append(item)
        self.restored.append(kept)
        return RestoredSettings({**submitted, "items": out}, tuple(kept))

    async def check_settings(self, sctx, settings):
        self.checked_preserved.append(sctx.preserved)


@pytest.fixture
def source(monkeypatch):
    found = Redacting()
    install(monkeypatch, found)
    yield found
    registry.reset_registry()


async def stored(client, cid):
    from sm_events.models import Calendar

    async def read(db):
        return (
            (await db.execute(select(Calendar).where(Calendar.id == uuid.UUID(cid))))
            .scalar_one()
            .sources
        )

    return await run(client, read)


async def put(client, cid, sources):
    got = await client.get(f"{BASE}/{cid}", headers=OWNER)
    return await client.put(
        f"{BASE}/{cid}/sources",
        json={"sources": sources, "expected": got.json()["sources_version"]},
        headers=OWNER,
    )


async def seed(client, cid):
    items = [{"name": "ok"}, {"name": SECRET, "secret": True}]
    assert (
        await put(client, cid, [{"id": "acme:red", "settings": {"items": items}}])
    ).status_code == 200


async def test_the_manager_sees_the_source_s_redaction_and_problems(client, source):
    cid = (await make(client))["id"]
    await seed(client, cid)
    got = await client.get(f"{BASE}/{cid}", headers=OWNER)
    (entry,) = got.json()["sources"]
    assert entry["settings"]["items"] == [{"name": "ok"}, {"hidden": True, "token": "h1"}]
    assert entry["problems"] == [
        {"loc": ["items", 0, "name"], "code": "bad_name", "message": "Fix it"}
    ]
    assert SECRET not in got.text  # not in the API answer, whichever way it is written


async def test_the_put_answer_is_redacted_too(client, source):
    cid = (await make(client))["id"]
    items = [{"name": SECRET, "secret": True}]
    got = await put(client, cid, [{"id": "acme:red", "settings": {"items": items}}])
    assert got.status_code == 200 and SECRET not in got.text


async def test_a_save_with_the_placeholder_keeps_the_hidden_content(client, source):
    cid = (await make(client))["id"]
    await seed(client, cid)
    before = json.dumps(await stored(client, cid))
    shown = {"items": [{"name": "renamed"}, {"hidden": True, "token": "h1"}]}
    got = await put(client, cid, [{"id": "acme:red", "settings": shown}])
    assert got.status_code == 200, got.text
    after = await stored(client, cid)
    assert after[0]["settings"]["items"][1] == {"name": SECRET, "secret": True}
    assert after[0]["settings"]["items"][0] == {"name": "renamed"}
    assert before != json.dumps(after)
    assert source.checked_preserved[-1] == (("items", 1),)  # the check was told what was put back


async def test_a_forged_placeholder_is_a_422_at_its_path(client, source):
    cid = (await make(client))["id"]
    await seed(client, cid)
    bad = {"items": [{"hidden": True, "token": "h0"}]}  # h0 is not hidden
    got = await put(client, cid, [{"id": "acme:red", "settings": bad}])
    assert got.status_code == 422
    (err,) = got.json()["detail"]
    assert err["loc"][-2:] == ["items", 0] and err["type"] == "value_error.unknown"


async def test_a_source_that_fails_to_redact_shows_nothing(client, source, monkeypatch):
    cid = (await make(client))["id"]
    await seed(client, cid)

    async def boom(*_a, **_k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(source, "view_settings", boom)
    got = await client.get(f"{BASE}/{cid}", headers=OWNER)
    (entry,) = got.json()["sources"]
    assert entry["settings"] == {} and SECRET not in got.text


async def test_an_uninstalled_source_shows_no_settings_and_empty_keeps_it(client, monkeypatch):
    from sm_events.models import Calendar

    install(monkeypatch)  # no plugin provides `acme:red` here
    cid = (await make(client))["id"]
    hidden = {"items": [{"name": SECRET, "secret": True}]}

    async def store(db):
        row = (await db.execute(select(Calendar).where(Calendar.id == uuid.UUID(cid)))).scalar_one()
        row.sources = [{"id": "acme:red", "settings": hidden}]

    await run(client, store)
    got = await client.get(f"{BASE}/{cid}", headers=OWNER)
    (entry,) = got.json()["sources"]
    assert (entry["installed"], entry["settings"]) == (False, {}) and SECRET not in got.text
    kept = await put(client, cid, [{"id": "acme:red", "settings": {}}])
    assert kept.status_code == 200
    assert (await stored(client, cid))[0]["settings"] == hidden
    registry.reset_registry()
