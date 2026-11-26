"""Editor writes distinguish a vanished page from a missing revision (#448)."""

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("gone", ["trash", "purge"])
@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("action", [
    "save", "publish", "unpublish", "submit", "approve", "reject", "schedule", "restore",
])
async def test_editor_write_returns_coded_page_not_found(authed_client, gone, guarded, action):
    client = authed_client
    created = await client.post("/api/pagebuilder/pages", json={"title": "Gone", "slug": "gone"})
    assert created.status_code == 201
    page = created.json()
    path = f"/api/pagebuilder/pages/{page['id']}"
    assert (await client.delete(path)).status_code == 204
    if gone == "purge":
        assert (await client.delete(f"{path}/purge")).status_code == 204
    body = {"expected_updated_at": page["updated_at"]} if guarded else {}
    if action == "reject":
        body["note"] = "Revise"
    if action == "save":
        response = await client.put(path, json=body)
    else:
        endpoint = "revisions/999/restore" if action == "restore" else action
        response = await client.post(f"{path}/{endpoint}", json=body)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Page not found", "code": "page_not_found"}
    # HTML views still use the host's normal not-found navigation response.
    view = await client.get(f"/pagebuilder/{page['id']}/edit")
    assert view.status_code == 404
    assert "page_not_found" not in view.text


async def test_missing_revision_does_not_report_page_missing(authed_client):
    created = await authed_client.post(
        "/api/pagebuilder/pages", json={"title": "Exists", "slug": "exists"}
    )
    page = created.json()
    path = f"/api/pagebuilder/pages/{page['id']}"
    response = await authed_client.post(
        f"{path}/revisions/999/restore", json={"expected_updated_at": page["updated_at"]}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Revision not found"}
    assert (await authed_client.put(path, json={"title": "Still writable"})).status_code == 200
