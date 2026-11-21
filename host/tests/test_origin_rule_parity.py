"""Records' event-link origin and newsletter's content-link origin are two copies of one rule (the
framework has no helper for an organisation's canonical origin): ``<scheme>://<organisation
slug>.<tenants.subdomain_base>[:port]``. They may differ only where the module's own fallback
differs (no slug or no subdomain base), so the shared vectors below must give the same answer from
both: change one copy and this fails until the other follows."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sm_newsletter.content import context as newsletter
from sm_newsletter.core.tenancy import TenancyMode as NewsletterMode
from sm_records.core.tenancy import TenancyMode as RecordsMode
from sm_records.public_submissions.registration import origin as records

VECTORS = [
    # (public base, subdomain base, slug, expected)
    ("https://example.org", "example.org", "acme", "https://acme.example.org"),
    ("https://example.org:8443", "example.org", "acme", "https://acme.example.org:8443"),
    ("http://localhost:8000", "localhost", "acme", "http://acme.localhost:8000"),
    ("https://example.org", " .Example.ORG. ", "acme", "https://acme.example.org"),
    ("https://example.org", "example.org", "globex-2", "https://globex-2.example.org"),
]


def app(sub: str):
    return SimpleNamespace(
        state=SimpleNamespace(tenants=SimpleNamespace(settings=SimpleNamespace(subdomain_base=sub)))
    )


@pytest.mark.parametrize(("base", "sub", "slug", "expected"), VECTORS)
async def test_both_copies_build_the_same_origin(monkeypatch, base, sub, slug, expected):
    async def newsletter_slug(*_a, **_k):
        return slug

    monkeypatch.setattr(newsletter, "mode_of", lambda _app: NewsletterMode.MULTI)
    monkeypatch.setattr(newsletter, "_org_slug", newsletter_slug)
    monkeypatch.setattr(records, "mode_of", lambda _app: RecordsMode.MULTI)
    monkeypatch.setattr(records, "public_base_url", lambda _app: base)
    monkeypatch.setattr(records, "_org_slug", newsletter_slug)

    assert await newsletter._content_base(app(sub), "t1", base) == expected
    assert await records.event_base(app(sub), "t1", object()) == expected
