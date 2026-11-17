"""Calendar HTTP setup shared by the API tests."""

from tests.support.app import as_user

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
BASE = "/api/events/calendars"
OWNER = as_user("o", V, E)
OWNER_P = as_user("o", V, E, P)
VIEWER = as_user("v", V)
EDITOR = as_user("e", V, E)
MANAGER = as_user("m", V, M)
SV = as_user("sv", V)
SE = as_user("se", V)


async def make(client, headers=OWNER, **body):
    body.setdefault("name", "Team")
    got = await client.post(BASE, json=body, headers=headers)
    assert got.status_code == 201, got.text
    return got.json()
