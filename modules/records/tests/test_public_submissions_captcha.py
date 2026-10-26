"""The optional CAPTCHA (#101, design §5 step 6): off by default; when on, the
definition names the provider and its site key (never the secret), and a
submission is stored only once the provider vouches for its response — a
rejection is ``400 captcha_failed``, an unreachable provider ``503
captcha_unavailable``, and neither writes anything."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from sm_records.public_submissions import captcha
from sm_records.settings import RecordsSettings

from tests.submissions_http import configure, contact_type, load, records_of, send

ON = {
    "public_submissions_captcha_provider": "turnstile",
    "public_submissions_captcha_site_key": "site-key-1",
    "public_submissions_captcha_secret": "secret-1",
}


class Provider:
    """A stand-in ``siteverify``: answers ``success`` for the response
    ``"good"``, and records what it was asked."""

    def __init__(self, *, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = body
        self.asked: list[tuple[str, dict[str, list[str]]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        self.asked.append((str(request.url), form))
        if self.body is not None:
            return httpx.Response(self.status, content=str(self.body).encode())
        return httpx.Response(self.status, json={"success": form.get("response") == ["good"]})


@pytest.fixture
def provider(monkeypatch) -> Provider:
    fake = Provider()
    monkeypatch.setattr(
        captcha,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    return fake


async def test_off_by_default_the_definition_names_no_captcha(site, provider):
    assert RecordsSettings().public_submissions_captcha_provider == "none"
    await contact_type(site)
    assert (await load(site))["captcha"] is None
    assert (await send(site)).status_code == 202
    assert provider.asked == [], "no provider is called while the CAPTCHA is off"


async def test_the_definition_carries_the_site_key_never_the_secret(site, provider):
    configure(site, **ON)
    await contact_type(site)
    shown = await load(site)
    assert shown["captcha"] == {"provider": "turnstile", "site_key": "site-key-1"}
    assert "secret-1" not in str(shown)


@pytest.mark.parametrize(
    ("provider_name", "url"),
    [
        ("turnstile", "https://challenges.cloudflare.com/turnstile/v0/siteverify"),
        ("hcaptcha", "https://api.hcaptcha.com/siteverify"),
    ],
)
async def test_a_vouched_response_is_stored(site, provider, provider_name, url):
    configure(site, **{**ON, "public_submissions_captcha_provider": provider_name})
    await contact_type(site)
    assert (await send(site, captcha_response="good")).status_code == 202
    assert len(await records_of(site)) == 1
    ((asked, form),) = provider.asked
    assert asked == url
    assert form["secret"] == ["secret-1"] and form["response"] == ["good"]


async def test_a_rejected_or_missing_response_is_captcha_failed(site, provider):
    configure(site, **ON)
    await contact_type(site)
    for extra in ({"captcha_response": "bad"}, {}, {"captcha_response": "x" * 9000}):
        refused = await send(site, **extra)
        assert refused.status_code == 400, refused.text
        assert refused.json()["code"] == "captcha_failed"
    assert len(provider.asked) == 1, "only a plausible response is sent to the provider"
    assert await records_of(site) == []


@pytest.mark.parametrize(
    "fake",
    [
        Provider(status=502),
        Provider(body="not json"),
        Provider(body="[1]"),
        # A vouching answer too large to be one is not read, let alone trusted.
        Provider(body='{"success": true, "pad": "' + "x" * 70_000 + '"}'),
    ],
)
async def test_an_unreachable_provider_fails_closed(site, monkeypatch, fake):
    monkeypatch.setattr(
        captcha,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    configure(site, **ON)
    await contact_type(site)
    refused = await send(site, captcha_response="good")
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "captcha_unavailable"
    assert refused.headers["cache-control"] == "no-store"
    assert await records_of(site) == []


async def test_a_timeout_fails_closed(site, monkeypatch):
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    monkeypatch.setattr(
        captcha,
        "client_factory",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(hang)),
    )
    configure(site, **ON)
    await contact_type(site)
    refused = await send(site, captcha_response="good")
    assert refused.status_code == 503 and refused.json()["code"] == "captcha_unavailable"


async def test_a_half_configured_captcha_refuses_rather_than_protects_nothing(site, provider):
    configure(site, **{**ON, "public_submissions_captcha_secret": ""})
    await contact_type(site)
    refused = await send(site, captcha_response="good")
    assert refused.status_code == 503
    assert provider.asked == []


async def test_a_honeypot_hit_is_dropped_before_the_provider_is_asked(site, provider):
    configure(site, **ON)
    await contact_type(site)
    assert (await send(site, hp="bot")).status_code == 202
    assert provider.asked == [] and await records_of(site) == []


def test_the_csp_warning_names_the_missing_host():
    on = RecordsSettings(**ON)

    def app(csp: str | None) -> SimpleNamespace:
        services = (
            None if csp is None else SimpleNamespace(settings=SimpleNamespace(public_csp=csp))
        )
        return SimpleNamespace(state=SimpleNamespace(pagebuilder=services))

    warning = captcha.csp_warning(app("script-src 'self'"), on)
    assert warning is not None and "challenges.cloudflare.com" in warning
    allowed = "script-src 'self' https://challenges.cloudflare.com"
    assert captcha.csp_warning(app(allowed), on) is None
    assert captcha.csp_warning(app(None), on) is None, "no pagebuilder, no CSP to check"
    assert captcha.csp_warning(app("script-src 'self'"), RecordsSettings()) is None


def test_the_secret_is_masked_on_the_settings_screen():
    from simple_module_core.secret_fields import conceals_secret

    assert conceals_secret("public_submissions_captcha_secret", "secret-1")
