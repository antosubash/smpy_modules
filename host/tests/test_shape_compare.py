"""Guard the guard: the byte-exact comparator must not call these equal."""

from __future__ import annotations

import time

import httpx
import pytest
from shape_compare import shape as _shape
from shape_compare import sign_session as _session


def test_the_comparator_catches_what_it_must():
    """Guard the guard: each of these must compare unequal, and a different
    timestamp or signature on an otherwise identical session must not."""
    key = "unit-secret"

    def resp(content=b"{}", headers=None, status=404):
        return httpx.Response(status, content=content, headers=headers or {})

    def shape(r):
        return _shape(r, key)

    assert shape(resp(b'{"detail":"a"}')) != shape(resp(b'{"detail":"b"}'))
    # invalid UTF-8: bytes that decode to the same replacement text still differ
    assert shape(resp(b"\xff")) != shape(resp(b"\xfe"))
    assert shape(resp(b"", {"content-length": "5"})) != shape(resp(b"", {"content-length": "6"}))
    # gzip, on HEAD: the compressed length is compared too
    gz = {"content-encoding": "gzip"}
    head = lambda n: httpx.Response(  # noqa: E731
        200, headers={**gz, "content-length": n}, request=httpx.Request("HEAD", "http://t/")
    )
    assert shape(head("5")) != shape(head("6"))
    assert shape(resp(headers={"x-correlation-id": "a" * 32})) != shape(
        resp(headers={"x-correlation-id": "b" * 32})
    )
    # cookies: value, attributes and presence all count
    plain = resp(headers={"set-cookie": "locale=en; path=/"})
    assert shape(plain) != shape(resp(headers={"set-cookie": "locale=de; path=/"}))
    assert shape(plain) != shape(resp(headers={"set-cookie": "locale=en; path=/; httponly"}))
    assert shape(plain) != shape(resp())
    payload = {"user_id": "u", "expires_at": int(time.time()) + 60}
    one = resp(headers={"set-cookie": f"session={_session(key, payload)}; path=/"})
    later = {**payload, "expires_at": payload["expires_at"] + 5}
    two = resp(headers={"set-cookie": f"session={_session(key, later)}; path=/"})
    assert shape(one) != shape(two)  # a moved deadline counts too
    other = resp(
        headers={"set-cookie": f"session={_session(key, {**payload, 'user_id': 'v'})}; path=/"}
    )
    assert shape(one) != shape(other)
    with pytest.raises(Exception):  # noqa: B017 - a forged signature is refused
        shape(resp(headers={"set-cookie": f"session={_session('other-secret', payload)}; path=/"}))
