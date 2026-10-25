"""Running the contributed bundle sections (#80) at each stage of a snapshot.

Pagebuilder's own documents are handled where they always were; this file is
the loop over :class:`~pagebuilder.snapshots.registry.SectionRegistry` that
``capture``, ``read_zip`` and ``SnapshotService`` call after them, so none of
those files has to know what a section is beyond one call.

Order is fixed: pagebuilder first — every contributor may reference its media,
so ``name_to_url`` has to exist — then contributors by name. Every call goes
through the caller's session, and every one is preceded by a tenant check, so
a section can neither leave the restore's transaction nor run for a tenant
other than the bound one.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from simple_module_db import current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.bundle import (
    CaptureContext,
    RestoreContext,
    SectionPlan,
    TenantMismatchError,
    ValidateContext,
)
from pagebuilder.snapshots.assets import from_sentinels, to_sentinels
from pagebuilder.snapshots.files import tree_size
from pagebuilder.snapshots.manifest import PAGEBUILDER_SECTION, check_manifest
from pagebuilder.snapshots.validate import BundleError

if TYPE_CHECKING:
    from pagebuilder.contracts.bundle import BundleSection
    from pagebuilder.snapshots.registry import SectionRegistry


def _tenant() -> str:
    """The bound tenant; a section never runs without one.

    Read once per stage, before the first section runs, and handed to every
    context: reading it per section would let one contributor that leaves
    another tenant bound pass the next one's check.
    """
    tenant = current_tenant_id.get()
    if not tenant:
        raise TenantMismatchError("bundle sections need a bound tenant")
    return tenant


def _contributed(manifest: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for entry in manifest.get("contents") or []:
        if isinstance(entry, dict) and entry.get("section") != PAGEBUILDER_SECTION:
            yield entry


def present(
    manifest: dict[str, Any], registry: SectionRegistry
) -> list[tuple[BundleSection, dict[str, Any]]]:
    """``(section, manifest entry)`` for each registered section the bundle carries, by name."""
    found = [
        (section, entry)
        for entry in _contributed(manifest)
        if (section := registry.get(entry["section"])) is not None
    ]
    return sorted(found, key=lambda pair: pair[0].name)


async def capture_sections(
    db: AsyncSession, registry: SectionRegistry, dest: Path, url_to_name: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    """Capture every registered section into ``dest/<name>/``.

    Returns the manifest ``contents`` entries and the bytes written. The size
    is read off the files rather than reported by the section, so the
    snapshot's size cannot disagree with what is on disk.
    """
    entries: list[dict[str, Any]] = []
    size = 0
    tenant = _tenant() if len(registry) else ""
    for section in registry:
        directory = dest / section.name
        if directory.exists():
            await asyncio.to_thread(shutil.rmtree, directory)
        directory.mkdir(parents=True)
        ctx = CaptureContext(
            db=db,
            tenant_id=tenant,
            dir=directory,
            to_portable=partial(to_sentinels, url_to_name=url_to_name),
        )
        ctx.check_tenant()
        result = await section.capture(ctx)
        ctx.check_tenant()  # and after: a section must not leave another tenant bound
        counts = dict(result.counts)
        # Checked here, not trusted: upload refuses non-integer counts, so a
        # contributor that wrote one would make its own snapshot unrestorable.
        if not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in counts.items()
        ):
            raise ValueError(f"bundle section {section.name!r} reported non-integer counts")
        size += await asyncio.to_thread(tree_size, directory)
        entries.append(
            {
                "section": section.name,
                "version": section.version,
                "required": section.required,
                "paths": [f"{section.name}/"],
                "counts": counts,
            }
        )
    return entries, size


def validate_sections(
    manifest: dict[str, Any], registry: SectionRegistry, dest: Path, index: dict[str, Any]
) -> None:
    """Hand each known section its extracted files; unknown ones are kept unread."""
    media_names = frozenset(index)
    for section, entry in present(manifest, registry):
        try:
            section.validate(
                ValidateContext(
                    dir=dest / section.name, version=entry["version"], media_names=media_names
                )
            )
        except BundleError:
            raise
        except Exception as exc:  # a contributor parsing untrusted files
            raise BundleError(f"the {section.name!r} section is malformed") from exc


def revalidate(
    manifest: dict[str, Any], registry: SectionRegistry, bundle_dir: Path, index: dict[str, Any]
) -> None:
    """Hold a stored bundle to the sections this host has *now*. Sync; raises ``BundleError``.

    Upload validated it against the registry of that moment, which is not the
    one a restore runs under: a module disabled since then leaves a
    ``required`` section nothing can restore (refused, never a pagebuilder-only
    restore), and a module enabled since then would otherwise plan and apply
    files its ``validate`` never saw. Run before staging and again at approval.
    """
    check_manifest(manifest, registry.readable())
    validate_sections(manifest, registry, bundle_dir, index)


def _restore_context(
    db: AsyncSession,
    section: BundleSection,
    entry: dict[str, Any],
    bundle_dir: Path,
    name_to_url: dict[str, str],
    tenant: str,
) -> RestoreContext:
    version = entry["version"]
    if version not in section.readable_versions:
        # A snapshot taken here before this host's section was upgraded past it.
        raise BundleError(f"unsupported version {version} of the {section.name!r} section")
    ctx = RestoreContext(
        db=db,
        tenant_id=tenant,
        dir=bundle_dir / section.name,
        version=version,
        from_portable=partial(from_sentinels, name_to_url=name_to_url),
    )
    ctx.check_tenant()
    return ctx


def _plan_entry(section: BundleSection, version: int, plan: SectionPlan) -> dict[str, Any]:
    return {
        "section": section.name,
        "label_key": section.label_key,
        "version": version,
        "lines": [
            {
                "label_key": line.label_key,
                "count": line.count,
                "items": [
                    {
                        "title": item.title,
                        "slug": item.slug,
                        "locale": item.locale,
                        "note_key": item.note_key,
                    }
                    for item in line.items
                ],
                "tone": line.tone,
            }
            for line in plan.lines
        ],
        "overwrites": plan.overwrites,
    }


async def plan_sections(
    db: AsyncSession,
    registry: SectionRegistry,
    manifest: dict[str, Any],
    bundle_dir: Path,
    name_to_url: dict[str, str],
) -> dict[str, Any]:
    """The plan's ``sections``, ``skipped`` and ``absent`` keys. Writes nothing.

    Raises ``RestoreConflictError`` (via ``ctx.conflict``) for what a section
    cannot apply, and ``BundleError`` for a section version this host no
    longer reads.
    """
    known = present(manifest, registry)
    sections = []
    tenant = _tenant() if known else ""
    for section, entry in known:
        ctx = _restore_context(db, section, entry, bundle_dir, name_to_url, tenant)
        plan = await section.plan(ctx)
        ctx.check_tenant()
        sections.append(_plan_entry(section, entry["version"], plan))
    carried = {entry["section"] for entry in _contributed(manifest)}
    return {
        "sections": sections,
        "skipped": [
            {"section": entry["section"], "version": entry.get("version")}
            for entry in _contributed(manifest)
            if registry.get(entry["section"]) is None
        ],
        "absent": [
            {"section": section.name, "label_key": section.label_key}
            for section in registry
            if section.name not in carried
        ],
    }


async def apply_sections(
    db: AsyncSession,
    registry: SectionRegistry,
    manifest: dict[str, Any],
    bundle_dir: Path,
    name_to_url: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Apply every known section the bundle carries, after pagebuilder's part.

    ``{section: {"counts": ..., "applied": ...}}``. Nothing commits here; a
    section that raises aborts the caller's whole transaction.
    """
    outcome: dict[str, dict[str, Any]] = {}
    known = present(manifest, registry)
    tenant = _tenant() if known else ""
    for section, entry in known:
        ctx = _restore_context(db, section, entry, bundle_dir, name_to_url, tenant)
        result = await section.apply(ctx)
        ctx.check_tenant()
        outcome[section.name] = {"counts": dict(result.counts), "applied": dict(result.applied)}
    await db.flush()
    return outcome
