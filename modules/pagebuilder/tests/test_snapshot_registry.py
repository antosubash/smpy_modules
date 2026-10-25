"""The bundle-section registry and the contract's guards (#80)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from bundle_fake import NotesSection
from conftest import _build_app
from fastapi import FastAPI
from pagebuilder.contracts import bundle
from pagebuilder.contracts.bundle import (
    CaptureContext,
    RestoreContext,
    TenantMismatchError,
    register_section,
)
from pagebuilder.snapshots.match import RestoreConflictError, match_pages
from pagebuilder.snapshots.registry import SectionRegistry
from pagebuilder.snapshots.sections import capture_sections, plan_sections
from simple_module_db import tenant_context


def _section(**overrides) -> NotesSection:
    section = NotesSection()
    for key, value in overrides.items():
        setattr(section, key, value)
    return section


@pytest.mark.parametrize("name", ["pagebuilder", "pages", "media", "blobs", "layout", "manifest"])
def test_a_reserved_name_is_refused(name):
    with pytest.raises(ValueError, match="reserved"):
        SectionRegistry().register(_section(name=name))


@pytest.mark.parametrize("name", ["", "News", "1news", "news-feed", "a" * 65, None])
def test_an_invalid_name_is_refused(name):
    with pytest.raises(ValueError, match="not"):
        SectionRegistry().register(_section(name=name))


def test_a_duplicate_name_is_refused():
    registry = SectionRegistry()
    registry.register(_section())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_section())


def test_a_section_must_read_what_it_writes():
    with pytest.raises(ValueError, match="cannot read the version 2"):
        SectionRegistry().register(_section(version=2))
    with pytest.raises(ValueError, match="non-boolean"):
        SectionRegistry().register(_section(required="yes"))


def test_sections_run_in_name_order():
    registry = SectionRegistry()
    for name in ("zebra", "alpha", "news"):
        registry.register(_section(name=name))
    assert [s.name for s in registry] == ["alpha", "news", "zebra"]
    assert registry.readable() == {name: frozenset({1}) for name in ("alpha", "news", "zebra")}


def test_registering_without_pagebuilder_mounted_is_a_no_op():
    assert register_section(FastAPI(), NotesSection()) is False


async def test_registering_on_a_pagebuilder_app(tmp_path):
    app, cleanup = await _build_app(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=True
    )
    try:
        section = NotesSection()
        assert register_section(app, section) is True
        assert app.state.pagebuilder.bundle_sections.get("notes") is section
        assert isinstance(section, bundle.BundleSection)
    finally:
        await cleanup()


# --- tenancy fails closed ---------------------------------------------------


def _restore_ctx(tenant: str) -> RestoreContext:
    return RestoreContext(
        db=None, tenant_id=tenant, dir=Path(), version=1, from_portable=lambda n: n
    )


def test_a_context_for_another_tenant_refuses():
    with tenant_context("acme"):
        _restore_ctx("acme").check_tenant()
        with pytest.raises(TenantMismatchError, match="'globex'"):
            _restore_ctx("globex").check_tenant()


@pytest.mark.unbound_tenant
def test_a_context_with_nothing_bound_refuses():
    ctx = CaptureContext(db=None, tenant_id="acme", dir=Path(), to_portable=lambda n: n)
    with pytest.raises(TenantMismatchError):
        ctx.check_tenant()


@pytest.mark.unbound_tenant
async def test_no_section_runs_without_a_bound_tenant(tmp_path):
    registry = SectionRegistry()
    section = NotesSection()
    registry.register(section)
    with pytest.raises(TenantMismatchError, match="bound tenant"):
        await capture_sections(None, registry, tmp_path, {})
    manifest = {"contents": [{"section": "notes", "version": 1}]}
    with pytest.raises(TenantMismatchError, match="bound tenant"):
        await plan_sections(None, registry, manifest, tmp_path, {})
    assert section.calls == []


# --- the exported matcher ---------------------------------------------------


def _row(id_: int, slug: str, group: str, locale: str = "en") -> SimpleNamespace:
    return SimpleNamespace(
        id=id_, slug=slug, locale=locale, translation_group=group, deleted_at=None
    )


def test_the_contract_exports_the_page_matcher():
    assert bundle.match_by_identity is match_pages


def test_the_matcher_works_on_any_identified_row():
    renamed, other = _row(1, "new-name", "g1"), _row(2, "hello", "g2")
    bundled = {
        ("en", "old-name"): {"slug": "old-name", "translation_group": "g1"},
        ("en", "fresh"): {"slug": "fresh"},
    }
    match = bundle.match_by_identity(bundled, [renamed, other])
    assert match.rows == {("en", "old-name"): renamed}
    assert match.renames == {("en", "old-name"): "new-name"}
    assert match.creates == [("en", "fresh")]
    assert match.untouched == [other]


def test_a_matcher_conflict_names_the_callers_rows():
    squatter = _row(5, "hello", "elsewhere")
    with pytest.raises(RestoreConflictError, match="different article"):
        bundle.match_by_identity(
            {("en", "hello"): {"slug": "hello", "translation_group": "g9"}},
            [squatter, _row(6, "moved", "g9")],
            noun="article",
        )
