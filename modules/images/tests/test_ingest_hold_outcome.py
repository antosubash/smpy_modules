"""A storage hold follows the request transaction's outcome, not the endpoint's.

The request's commit runs after the endpoint returned; if that commit fails,
the insert's finish of each op goes with it, and every op the request took
must be handed back at once (else it stays claimed for ``INGEST_CLAIM`` and a
retry under a quota of one image is refused for half an hour). And a batch
file that fails after its slot was reserved, but before its insert took the
op over, hands back that file's op only - the other files keep their holds.
"""

from __future__ import annotations

import pytest
import simple_module_db.deps as db_deps
from simple_module_db.session import RequestSession
from sm_images.storage import ImageStore

from tests.billing_support import ops
from tests.test_upload_base64 import b64, post
from tests.upload_support import all_rows, jpeg, make_collection, post_files

_FAIL = "fail_commit"


def _request_commit_fails_once(monkeypatch) -> None:
    """The request's own session (the one ``get_db`` enlists) fails its commit."""
    real_register = db_deps.register_request_session
    real_commit = RequestSession.commit
    armed = {"on": True}

    def register(scope, session):
        if armed.get("on"):
            session.info[_FAIL] = True
        real_register(scope, session)

    async def commit(self):
        if self.info.pop(_FAIL, False) and armed.pop("on", False):
            raise RuntimeError("commit blip")
        return await real_commit(self)

    monkeypatch.setattr(db_deps, "register_request_session", register)
    monkeypatch.setattr(RequestSession, "commit", commit)


def _live(gauge) -> dict[str, str]:
    return {h.id: h.status for h in gauge.holds.values() if h.status != "released"}


async def test_a_failed_request_commit_releases_the_holds(uploads, gauge, monkeypatch):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    gauge.limit = len(data)  # room for exactly one image
    _request_commit_fails_once(monkeypatch)
    try:
        failed = await post(uploads, cid, filename="a.jpg", data=b64(data))
        assert failed.status_code == 500, failed.text
    except RuntimeError:
        pass  # an unhandled 500, raised through the transport
    assert await all_rows(uploads) == []
    assert _live(gauge) == {}, "the failed commit left the hold claimed"
    assert [o.id for o in await ops(uploads.db_state) if o.claim_token is not None] == []

    retried = await post(uploads, cid, filename="a.jpg", data=b64(data))
    assert retried.status_code == 200, retried.text
    (row,) = await all_rows(uploads)
    assert _live(gauge) == {row.storage_hold_id: "committed"}


async def test_a_batch_file_failing_before_its_insert_hands_back_its_op_only(
    uploads, gauge, monkeypatch
):
    files = [jpeg(size=(64, 48), color=c) for c in ("red", "green", "blue")]
    real_put = ImageStore.put

    async def put(self, key, data, **kw):
        if data == files[1]:
            raise RuntimeError("storage blip")
        return await real_put(self, key, data, **kw)

    monkeypatch.setattr(ImageStore, "put", put)
    cid = await make_collection(uploads)
    got = await post_files(
        uploads, cid, [(f"{i}.jpg", d, "image/jpeg") for i, d in enumerate(files)]
    )
    assert got.status_code == 200, got.text
    assert [r["status"] for r in got.json()["results"]] == ["created", "error", "created"]

    rows = await all_rows(uploads)
    assert len(rows) == 2
    assert _live(gauge) == {r.storage_hold_id: "committed" for r in rows}
    assert len(gauge.holds) == 3, "each file took its own hold"
    claimed = [o.id for o in await ops(uploads.db_state) if o.claim_token is not None]
    assert claimed == [], "the failed file's op is still claimed"


pytestmark = pytest.mark.asyncio
