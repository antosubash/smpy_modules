"""The address policy: URL rules at save and at every fetch, and the address guard."""

from __future__ import annotations

import socket

import pytest
from sm_events.core import constants
from sm_events.feeds.subscriptions import policy
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

from tests.support.net import OTHER_PUBLIC_IP, PUBLIC_IP, PUBLIC_IPV6, resolver  # noqa: F401

OFF = policy.Policy(allow_private=False)
ON = policy.Policy(allow_private=True, may_use_private=True)


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(UnsafeURLError) as caught:
        fn(*args, **kwargs)
    assert str(caught.value) == caught.value.code  # never echoes the address
    return caught.value.code


# --- normalising -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" webcal://Cal.Example/x.ics#frag ", "https://cal.example/x.ics"),
        ("WEBCALS://cal.example/x.ics", "https://cal.example/x.ics"),
        ("webcal://cal.example/a?token=1", "https://cal.example/a?token=1"),
        ("https://cal.example/x.ics#a", "https://cal.example/x.ics"),
        ("https://bücher.example/x.ics", "https://xn--bcher-kva.example/x.ics"),
        ("https://XN--BCHER-KVA.example/x", "https://xn--bcher-kva.example/x"),
        ("https://cal.example:443/x", "https://cal.example/x"),
    ],
)
def test_normalise(raw, expected):
    assert policy.normalise(raw) == expected


def test_an_empty_userinfo_marker_is_dropped_by_the_parser():
    assert policy.normalise("https://@cal.example/x") == "https://cal.example/x"


def test_normalise_is_idempotent():
    once = policy.normalise("webcal://Bücher.Example/p?q=1#f")
    assert policy.normalise(once) == once


def test_too_long_is_invalid():
    ok = "https://cal.example/" + "a" * (
        constants.SUBSCRIPTION_URL_MAX - len("https://cal.example/")
    )
    assert policy.normalise(ok) == ok
    assert _code(policy.normalise, ok + "a") == "invalid_url"
    assert _code(policy.normalise, "webcal://cal.example/" + "a" * 2000) == "invalid_url"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url",
        "https://",
        "https:///path",
        "https://cal.example/\x00",
        "https://cal.example/a\nb",
        "https://xn--/x",
        "https://exa\u2044mple.com/x",  # a character the IDNA library refuses
        "https://cal.example:abc/x",
    ],
)
def test_unparsable_is_invalid(raw):
    assert _code(policy.normalise, raw) == "invalid_url"


# --- scheme, userinfo, port --------------------------------------------------


def test_scheme_rules():
    assert policy.check("https://cal.example/x", OFF) == ("cal.example", 443)
    assert _code(policy.check, "http://cal.example/x", OFF) == "invalid_scheme"
    assert policy.check("http://cal.example/x", ON) == ("cal.example", 80)
    for url in (
        "ftp://cal.example/x",
        "file:///etc/passwd",
        "data:text/calendar,BEGIN:VCALENDAR",
        "javascript:alert(1)",
        "gopher://cal.example/",
    ):
        assert _code(policy.check, url, OFF) in {"invalid_scheme", "invalid_url", "missing_host"}
        assert _code(policy.check, url, ON) in {"invalid_scheme", "invalid_url", "missing_host"}


@pytest.mark.parametrize(
    "url", ["https://u:p@h.example/", "https://u@h.example/", "https://%75@h.example/"]
)
def test_userinfo_refused(url):
    assert _code(policy.check, url, OFF) == "userinfo_not_allowed"
    assert _code(policy.check, url, ON) == "userinfo_not_allowed"


def test_ports():
    assert policy.check("https://cal.example:443/", OFF) == ("cal.example", 443)
    assert _code(policy.check, "https://cal.example:8443/", OFF) == "port_not_allowed"
    assert _code(policy.check, "https://cal.example:80/", OFF) == "port_not_allowed"
    assert policy.check("https://cal.example:8443/", ON) == ("cal.example", 8443)
    assert policy.check("https://cal.example:65535/", ON) == ("cal.example", 65535)
    assert _code(policy.check, "https://cal.example:0/", OFF) == "invalid_url"
    assert _code(policy.check, "https://cal.example:0/", ON) == "invalid_url"
    assert _code(policy.check, "https://cal.example:99999/", ON) == "invalid_url"


def test_non_manager_cannot_use_switch(resolver):  # noqa: F811
    resolver["intra.example"] = ["10.0.0.5"]
    weak = policy.effective(True, may_use_private=False)
    assert weak == policy.Policy(allow_private=True, may_use_private=False)
    assert (
        _code(policy.resolve_allowed, _url("https://intra.example/x"), weak) == "non_public_address"
    )
    assert _code(policy.check, "http://intra.example/x", weak) == "invalid_scheme"
    assert _code(policy.check, "https://intra.example:8443/x", weak) == "port_not_allowed"
    strong = policy.effective(True, may_use_private=True)
    assert policy.resolve_allowed(_url("https://intra.example/x"), strong) == (
        "intra.example",
        ("10.0.0.5",),
    )
    assert not policy.effective(False, may_use_private=True).intranet


def _url(raw: str):
    import httpx

    return httpx.URL(raw)


# --- resolving ---------------------------------------------------------------


def test_resolve_returns_every_distinct_public_address(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP, OTHER_PUBLIC_IP, PUBLIC_IP, PUBLIC_IPV6]
    host, ips = policy.resolve_allowed(_url("https://cal.example/x"), OFF)
    assert host == "cal.example"
    assert ips == (PUBLIC_IP, OTHER_PUBLIC_IP, PUBLIC_IPV6)


def test_mixed_answer_refused(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP, "10.0.0.1"]
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), OFF) == "non_public_address"
    resolver["cal.example"] = ["10.0.0.1", PUBLIC_IP]
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), OFF) == "non_public_address"
    resolver["cal.example"] = [PUBLIC_IP, "::ffff:127.0.0.1"]
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), ON) == "non_public_address"


def test_unresolvable_fails_closed(resolver):  # noqa: F811
    assert (
        _code(policy.resolve_allowed, _url("https://nowhere.example/x"), OFF) == "unresolvable_host"
    )
    resolver["empty.example"] = []
    assert (
        _code(policy.resolve_allowed, _url("https://empty.example/x"), OFF) == "unresolvable_host"
    )


def test_a_resolver_that_raises_anything_fails_closed(monkeypatch):
    from tests.support.net import fake_dns

    def boom(*args, **kwargs):
        raise UnicodeError("x")

    fake_dns(monkeypatch, boom)
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), OFF) == "unresolvable_host"

    def odd(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 443))]

    fake_dns(monkeypatch, odd)
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), OFF) == "non_public_address"


def test_resolution_is_checked_per_call_not_cached(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    policy.resolve_allowed(_url("https://cal.example/x"), OFF)
    resolver["cal.example"] = ["10.0.0.1"]  # DNS changed between save and fetch
    assert _code(policy.resolve_allowed, _url("https://cal.example/x"), OFF) == "non_public_address"
    assert resolver.calls["cal.example"] == 2


def test_a_public_literal_passes_the_guard_without_a_lookup(resolver):  # noqa: F811
    assert policy.resolve_allowed(_url(f"https://{PUBLIC_IP}/x"), OFF) == (PUBLIC_IP, (PUBLIC_IP,))
    assert policy.resolve_allowed(_url(f"https://[{PUBLIC_IPV6}]/x"), OFF) == (
        PUBLIC_IPV6,
        (PUBLIC_IPV6,),
    )
    assert resolver.calls == {}


# --- what an error may say ---------------------------------------------------


def test_error_never_echoes_url(resolver):  # noqa: F811
    secret = "https://cal.example/private-TOKEN-123/basic.ics"
    resolver["cal.example"] = ["10.0.0.1"]
    with pytest.raises(UnsafeURLError) as caught:
        policy.resolve_allowed(_url(secret), OFF)
    assert "TOKEN" not in str(caught.value) + repr(caught.value) + repr(caught.value.args)
    assert caught.value.__cause__ is None


def test_a_guard_refusal_and_an_unresolvable_host_map_to_one_user_facing_code(resolver):  # noqa: F811
    resolver["internal.example"] = ["10.0.0.1"]
    codes = []
    for host in ("internal.example", "nowhere.example"):
        codes.append(_code(policy.resolve_allowed, _url(f"https://{host}/x"), OFF))
    assert sorted(codes) == ["non_public_address", "unresolvable_host"]
    assert len({constants.URL_REFUSAL_CODES[c] for c in codes}) == 1
    assert policy.user_code(UnsafeURLError(codes[0])) == policy.user_code(UnsafeURLError(codes[1]))


def test_every_guard_code_has_a_user_code():
    for code in (
        "invalid_url",
        "missing_host",
        "invalid_scheme",
        "userinfo_not_allowed",
        "port_not_allowed",
        "unresolvable_host",
        "non_public_address",
    ):
        assert policy.user_code(UnsafeURLError(code)) in constants.URL_REFUSAL_DETAIL
    assert (
        policy.user_code(UnsafeURLError("something_new")) == "url_invalid"
    )  # closed: never free text
