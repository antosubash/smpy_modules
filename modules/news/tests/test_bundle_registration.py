"""News joins pagebuilder's content bundle only where pagebuilder is mounted (#80)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest
from bundle_app import bundle_host
from news.integrations import pagebuilder as pb
from news.integrations.bundle import NewsBundleSection
from news.module import NewsModule
from pagebuilder.contracts.bundle import BundleSection


def test_nothing_registers_without_pagebuilder(monkeypatch) -> None:
    monkeypatch.setattr(pb, "available", lambda: False)
    assert pb.register_bundle_section(SimpleNamespace(state=SimpleNamespace())) is False


def test_nothing_registers_where_pagebuilder_is_installed_but_not_mounted() -> None:
    assert pb.register_bundle_section(SimpleNamespace(state=SimpleNamespace())) is False


def test_the_section_satisfies_the_contract() -> None:
    section = NewsBundleSection()
    assert isinstance(section, BundleSection)
    assert (section.name, section.required, section.readable_versions) == (
        "news",
        False,
        frozenset({1}),
    )
    assert set(section.count_label_keys) == {"articles", "categories", "tags", "redirects"}


def test_importing_news_does_not_import_the_bundle_section() -> None:
    """``news.integrations.bundle`` imports pagebuilder at module scope, so only
    ``register_bundle_section`` may import it — never booting news itself."""
    probe = textwrap.dedent("""
        import sys
        import news.models, news.module, news.service, news.settings
        import news.endpoints.api, news.endpoints.views
        from news.integrations import pagebuilder
        assert "news.integrations.bundle" not in sys.modules, "imported eagerly"
        print("ok")
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("ok")


@pytest.mark.asyncio
async def test_on_startup_registers_the_section_on_a_pagebuilder_host(tmp_path) -> None:
    async with bundle_host(tmp_path, news=False) as client:
        app = client.app  # type: ignore[attr-defined]
        registry = app.state.pagebuilder.bundle_sections
        assert registry.get("news") is None
        module = NewsModule()
        module.register_settings(app)
        await module.on_startup(app)
        assert isinstance(registry.get("news"), NewsBundleSection)
