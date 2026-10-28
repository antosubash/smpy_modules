"""Direct-upload review fixes (Task 7, round 1).

* two ``complete`` calls for one upload never delete the winner's original;
* every call after ``start`` re-checks ``edit`` through ``RequiresResource``;
* the declared type is binding (key extension, row and bytes agree);
* a stored size that is not the declared one is ``parts_mismatch``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import iter_route_contexts
from sharing.models import ResourceShare
from simple_module_hosting.token_guard import route_admits_tokens
from sm_images import constants
from sm_images.ingest import direct
from sm_images.models import Collection, Image
from sm_images.storage import ImageStore
from sqlalchemy import delete

from tests.access_support import share
from tests.stub_auth import as_user, user_uuid
from tests.test_direct_upload import UPLOADS, complete, send_parts, start
from tests.upload_support import OLGA, all_rows, jpeg, make_collection, png, stored

EDDIE = as_user("eddie", ("images.view",))


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


def blind_first_existing(monkeypatch) -> list[int]:
    """The first ``_existing`` check misses, as when the winner had not committed."""
    calls: list[int] = []
    real = direct._existing

    async def blinded(db, ticket):
        calls.append(1)
        return None if len(calls) == 1 else await real(db, ticket)

    monkeypatch.setattr(direct, "_existing", blinded)
    return calls


def ticket_of(upload_id: str) -> direct.Ticket:
    return direct.load_ticket(upload_id, secret="images-test-secret", owner=user_uuid("olga"))


async def test_losing_complete_keeps_the_winners_original(uploads, monkeypatch):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    ticket = ticket_of(body["upload_id"])
    async with uploads.db_state.session_factory() as s:  # the winner commits first
        s.add(
            Image(
                id=uuid.UUID(ticket.image),
                collection_id=uuid.UUID(cid),
                storage_key=ticket.key,
                filename="big.jpg",
                content_type="image/jpeg",
                size_bytes=len(data),
            )
        )
        await s.commit()
    calls = blind_first_existing(monkeypatch)
    got = await complete(uploads, body["upload_id"], parts)
    assert got.status_code == 200, got.text
    assert (got.json()["status"], got.json()["id"]) == ("duplicate", ticket.image)
    assert calls == [1]  # blinded once; the lost insert re-read the row by id (find_id)
    assert stored(uploads.storage) == [ticket.key]  # the winner's object is still there
    assert [str(r.id) for r in await all_rows(uploads)] == [ticket.image]


async def test_second_complete_after_parts_are_consumed_answers_the_row(uploads, monkeypatch):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    first = await complete(uploads, body["upload_id"], parts)
    assert first.status_code == 200
    blind_first_existing(monkeypatch)  # skip the fast path: list_parts now fails
    again = await complete(uploads, body["upload_id"], parts)
    assert (again.status_code, again.json()["id"]) == (200, first.json()["id"])
    assert len(stored(uploads.storage)) == 1


async def _revocable(uploads) -> tuple[str, dict]:
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    async with uploads.db_state.session_factory() as s:
        s.add(share(await s.get(Collection, uuid.UUID(cid)), "eddie", "edit"))
        await s.commit()
    made = await start(uploads, cid, data, headers=EDDIE)
    assert made.status_code == 201, made.text
    return cid, made.json()


async def test_a_revoked_share_cannot_continue_an_upload(uploads):
    _, body = await _revocable(uploads)
    data = jpeg(size=(64, 48))
    parts = await send_parts(uploads, body, data, headers=EDDIE)
    async with uploads.db_state.session_factory() as s:
        await s.execute(delete(ResourceShare))
        await s.commit()
    put = await uploads.put(body["part_urls"][0], content=data[:400], headers=EDDIE)
    done = await complete(uploads, body["upload_id"], parts, headers=EDDIE)
    gone = await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=EDDIE)
    assert [put.status_code, done.status_code, gone.status_code] == [404, 404, 404]
    assert await all_rows(uploads) == []


def test_upload_routes_gate_tokens_like_the_collection_routes(uploads):
    """Same gate (``images.view``) plus ``RequiresResource`` on every route, so an
    API token reaches them exactly when it reaches ``PATCH /collections/{id}``."""
    contexts = {(c.path, m): c for c in iter_route_contexts(uploads.app.routes) for m in c.methods}
    reference = route_admits_tokens(
        contexts[("/api/images/collections/{collection_id}", "PATCH")].original_route
    )
    for path, method in [
        ("/api/images/uploads/{upload_id}/parts/{part_no}", "PUT"),
        ("/api/images/uploads/{upload_id}/complete", "POST"),
        ("/api/images/uploads/{upload_id}", "DELETE"),
        ("/api/images/collections/{collection_id}/uploads", "POST"),
    ]:
        assert route_admits_tokens(contexts[(path, method)].original_route) is reference, path


@pytest.mark.parametrize(
    "body",
    [
        {"filename": "anim.gif"},
        {"filename": "doc.pdf"},
        {"filename": "x.jpg", "content_type": "application/pdf"},
    ],
)
async def test_start_refuses_an_undeclarable_type(uploads, body):
    cid = await make_collection(uploads)
    got = await uploads.post(
        f"/api/images/collections/{cid}/uploads", json={"size": 10, **body}, headers=OLGA
    )
    assert (got.status_code, got.json()["code"]) == (415, constants.CODE_UNSUPPORTED_TYPE)


async def test_complete_refuses_bytes_of_another_type(uploads):
    data = png(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()  # declared big.jpg
    parts = await send_parts(uploads, body, data)
    got = await complete(uploads, body["upload_id"], parts)
    assert (got.status_code, got.json()["code"]) == (415, constants.CODE_UNSUPPORTED_TYPE)
    assert stored(uploads.storage) == [] and await all_rows(uploads) == []


async def test_declared_type_sets_key_and_row(uploads):
    data = png(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data, filename="scan.bin", content_type="image/png")).json()
    parts = await send_parts(uploads, body, data)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200
    (row,) = await all_rows(uploads)
    assert row.storage_key.endswith("/original.png") and row.content_type == "image/png"


async def test_a_stored_size_mismatch_is_parts_mismatch(uploads, monkeypatch):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)

    async def wrong_head(self, key):
        return len(data) + 1, None

    monkeypatch.setattr(ImageStore, "head", wrong_head)
    got = await complete(uploads, body["upload_id"], parts)
    assert (got.status_code, got.json()["code"]) == (409, constants.CODE_PARTS_MISMATCH)
    assert stored(uploads.storage) == []
