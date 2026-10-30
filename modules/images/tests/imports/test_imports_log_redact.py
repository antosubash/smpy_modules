"""A fetched URL's query string and userinfo never reach a log record.

httpx logs every request at INFO (``HTTP Request: GET <url> ...``). An import's
``source_url`` is often a presigned link whose query *is* the credential
(``X-Amz-Signature``), so ``sm_images.imports.log_redact`` filters the ``httpx``
logger: the URL keeps its scheme, host and path, nothing else.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from sm_images.imports import log_redact
from sm_images.imports.fetch import safe_stream

from tests.support.fetch import PUBLIC_IP, body

SECRET = "s3cr3t-signature"


@pytest.fixture(autouse=True)
def _filter_installed():
    log_redact.install()
    yield


def _messages(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


async def test_a_presigned_query_never_reaches_a_log_record(resolver, inner, caplog):
    resolver["bucket.example"] = [PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/first.jpg":
            loc = f"https://bucket.example/second.jpg?X-Amz-Signature={SECRET}-2"
            return httpx.Response(302, headers={"location": loc})
        return body(b"img")

    inner(handler)
    url = f"https://bucket.example/first.jpg?X-Amz-Credential=AK&X-Amz-Signature={SECRET}"
    with caplog.at_level(logging.DEBUG):
        data = b"".join([c async for c in safe_stream(url, max_bytes=1000, timeout=5)])
    assert data == b"img"
    text = _messages(caplog)
    assert "HTTP Request" in text  # httpx did log, through the filter
    assert "/first.jpg" in text and "/second.jpg" in text
    assert SECRET not in text
    assert "X-Amz" not in text


def test_userinfo_and_query_are_stripped_from_any_httpx_record(caplog):
    url = httpx.URL(f"https://user:{SECRET}@host.example/p.jpg?sig={SECRET}#frag")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info("HTTP Request: %s %s", "GET", url)
        logging.getLogger("httpx").info(f"raw {url}")
        logging.getLogger("httpx").info("str %s", str(url))
    text = _messages(caplog)
    assert SECRET not in text and "user" not in text
    assert text.count("https://host.example/p.jpg") == 3


def test_install_is_idempotent():
    log_redact.install()
    log_redact.install()
    filters = [f for f in logging.getLogger("httpx").filters if isinstance(f, log_redact.Filter)]
    assert len(filters) == 1


async def test_on_startup_and_the_worker_runtime_install_it(images_app, monkeypatch):
    from sm_images.module import ImagesModule
    from sm_images.pipeline import worker_runtime

    calls: list[str] = []
    monkeypatch.setattr(log_redact, "install", lambda: calls.append("x"))
    app, _ = images_app
    await ImagesModule().on_startup(app)
    assert calls == ["x"]
    monkeypatch.setattr(worker_runtime, "worker_session_factory", lambda: None)
    worker_runtime.worker_runtime()
    assert calls == ["x", "x"]
