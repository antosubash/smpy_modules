"""A failed import row says why on the job (QA retest 2, R2-IMPORT).

The card showed "12 failed" and nothing else: the job's ``errors`` held only
job-level codes. Each failed row now adds ``{code, item, status, reason,
where}`` - ``where`` is host and path, never the query string - up to
``ITEM_ERRORS_MAX`` rows.
"""

from __future__ import annotations

import httpx
import pytest
from sm_images.imports import item_errors

from tests.fetch_support import body
from tests.import_support import HOST, URL, feature, serve_images

pytestmark = pytest.mark.asyncio


async def test_a_403_row_stores_its_status_code_and_place(imp, resolver, inner):
    serve_images(
        resolver,
        inner,
        fail={
            "/blocked.jpg": httpx.Response(403),
            "/page.jpg": body(b"<html>not an image</html>"),
        },
    )
    feats = [
        feature({"url": f"https://{HOST}/blocked.jpg?token=secret"}),
        feature({"url": f"https://{HOST}/page.jpg"}),
    ]
    job = await imp.job(feats, URL)
    assert await imp.run(job) == "completed"
    rows = sorted(
        (e for e in (await imp.reload(job)).errors if "item" in e), key=lambda e: e["item"]
    )
    assert [{k: v for k, v in e.items() if k != "at"} for e in rows] == [
        {
            "code": "http_403",
            "item": 0,
            "status": 403,
            "reason": "Forbidden",
            "where": f"{HOST}/blocked.jpg",
        },
        {"code": "unsupported_type", "item": 1, "where": f"{HOST}/page.jpg"},
    ]
    assert "secret" not in str(rows)


async def test_only_the_first_rows_are_kept(imp, resolver, inner, monkeypatch):
    monkeypatch.setattr(item_errors, "ITEM_ERRORS_MAX", 2)
    serve_images(resolver, inner, fail={f"/{n}.jpg": httpx.Response(404) for n in range(4)})
    job = await imp.job([feature({"url": f"https://{HOST}/{n}.jpg"}) for n in range(4)], URL)
    assert await imp.run(job) == "completed"
    assert len([e for e in (await imp.reload(job)).errors if "item" in e]) == 2
