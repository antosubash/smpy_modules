"""MINOR 3 / MINOR 4: refusing before the response, and before the read.

A filter the list answers with a ``400`` used to make the export a ``200 OK``
attachment holding a truncated JSON prefix, because the ``QueryError`` was
raised inside the streaming body — after ``http.response.start``, where
nothing can be a status any more. And ``max_import_bytes`` was applied to
what had already been read, so a body with no ``Content-Length`` was buffered
whole and *then* refused.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, api_record, api_type, roles
from tests.relation_helpers import text_field

_API = "/api/records/types"
# --- MINOR 3: the export refuses before it is a download -------------------


async def test_a_refused_filter_on_the_export_is_a_400_with_a_body(client):
    await api_type(
        client,
        "post",
        [text_field("title"), {"key": "body", "type": "text", "label": "Body", "indexed": False}],
        display_field="title",
    )
    await api_record(client, "post", {"title": "t"})
    for query in ("filter=nope:eq:1", "filter=body:eq:x", "sort=nope"):
        resp = await client.get(f"{_API}/post/records/export?{query}", headers=roles(ADMIN))
        assert resp.status_code == 400, (query, resp.status_code, resp.text[:200])
        assert "content-disposition" not in resp.headers
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["detail"]


# --- MINOR 4: the upload ceiling is applied while reading ------------------


async def test_a_body_with_no_content_length_stops_at_the_ceiling(client):
    """A chunked upload declares no length, so the ceiling can only be the
    count of what actually arrived — and it has to stop the read, not report
    on it afterwards."""
    await api_type(client, "post", [text_field("title")], display_field="title")
    client.app.state.sm_records.settings.max_import_bytes = 1024
    sent = {"bytes": 0}
    chunk = b"x" * (64 * 1024)

    async def body():
        for _ in range(512):  # 32 MB if anything reads it all
            sent["bytes"] += len(chunk)
            yield chunk

    resp = await client.post(
        f"{_API}/post/records/import?format=json",
        content=body(),
        headers={**roles(ADMIN), "content-type": "application/json"},
    )
    assert resp.status_code == 413, resp.text
    assert sent["bytes"] <= 2 * len(chunk), sent["bytes"]


async def test_a_chunked_multipart_upload_stops_at_the_ceiling(client):
    await api_type(client, "post", [text_field("title")], display_field="title")
    client.app.state.sm_records.settings.max_import_bytes = 1024
    boundary = "----probe"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="a.json"\r\nContent-Type: application/json\r\n\r\n'
    ).encode()
    sent = {"bytes": 0}
    chunk = b"x" * (64 * 1024)

    async def body():
        sent["bytes"] += len(head)
        yield head
        for _ in range(512):
            sent["bytes"] += len(chunk)
            yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    resp = await client.post(
        f"{_API}/post/records/import",
        content=body(),
        headers={**roles(ADMIN), "content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert resp.status_code == 413, resp.text
    assert sent["bytes"] <= len(head) + 2 * len(chunk), sent["bytes"]
