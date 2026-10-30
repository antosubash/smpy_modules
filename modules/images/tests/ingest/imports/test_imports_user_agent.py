"""Every import fetch names itself (QA retest 2, R2-IMPORT).

Wikimedia answers 403 to httpx's default ``python-httpx/x`` User-Agent; its
policy asks for ``<client>/<version> (<contact>)``. Every hop - redirects
included - sends the module's own.
"""

from __future__ import annotations

import re

import httpx
from sm_images.ingest.imports import fetch
from sm_images.ingest.imports.fetch import safe_stream

from tests.support.fetch import OTHER_PUBLIC_IP, PUBLIC_IP, body


async def _fetch(url: str) -> bytes:
    return b"".join([c async for c in safe_stream(url, max_bytes=1_000_000, timeout=5)])


def test_the_user_agent_is_descriptive() -> None:
    assert re.fullmatch(
        r"SimpleModule-Images/\S+ \(\+https://\S+\) python-httpx/\S+", fetch.USER_AGENT
    )


async def test_every_hop_sends_it(resolver, inner):
    resolver["upload.example"] = [PUBLIC_IP]
    resolver["thumb.example"] = [OTHER_PUBLIC_IP]

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "upload.example":
            return httpx.Response(302, headers={"location": "https://thumb.example/b.jpg"})
        return body(b"img")

    seen = inner(answer)
    assert await _fetch("https://upload.example/a.jpg") == b"img"
    assert [r.headers["user-agent"] for r in seen] == [fetch.USER_AGENT] * 2
