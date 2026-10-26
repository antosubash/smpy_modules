"""Planning and applying the contributed sections of a restore (#80).

Split from :mod:`pagebuilder.snapshots.sections` (300-line cap, #133), which
captures and validates them; the rules stated there hold here too — every
call goes through the caller's session and is preceded by a tenant check.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.bundle import RestoreContext, SectionPlan
from pagebuilder.snapshots.access import (
    OMITTED_REASON_KEY,
    SYSTEM,
    SectionAccess,
    denied_entry,
    needed,
)
from pagebuilder.snapshots.assets import from_sentinels
from pagebuilder.snapshots.sections import _contributed, _tenant, present
from pagebuilder.snapshots.validate import BundleError

if TYPE_CHECKING:
    from pagebuilder.contracts.bundle import BundleSection
    from pagebuilder.snapshots.registry import SectionRegistry


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


def _omitted(entry: dict[str, Any]) -> dict[str, Any]:
    """An absent section the capture left out: why, from the manifest (untrusted)."""
    perms = entry.get("permissions")
    return {
        "omitted": True,
        "reason_key": OMITTED_REASON_KEY,
        "permissions": [p for p in perms if isinstance(p, str)] if isinstance(perms, list) else [],
    }


async def plan_sections(
    db: AsyncSession,
    registry: SectionRegistry,
    manifest: dict[str, Any],
    bundle_dir: Path,
    name_to_url: dict[str, str],
    access: SectionAccess = SYSTEM,
    left_out: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The plan's ``sections``, ``skipped``, ``absent`` and ``denied`` keys. Writes nothing.

    A section *access* may not apply, or one named in *left_out* (denied
    when the restore was staged), is not planned at all — its rows are not
    the principal's to see — and is listed under ``denied``. An ``absent``
    section a capture left out for lack of permission says ``omitted``.

    Raises ``RestoreConflictError`` (via ``ctx.conflict``) for what a section
    cannot apply, and ``BundleError`` for a section version this host no
    longer reads.
    """
    known = present(manifest, registry)
    sections, denied = [], []
    tenant = _tenant() if known else ""
    for section, entry in known:
        if section.name in left_out:
            continue
        missing = access.missing(section, "apply")
        if missing:
            denied.append(denied_entry(section, missing))
            continue
        ctx = _restore_context(db, section, entry, bundle_dir, name_to_url, tenant)
        plan = await section.plan(ctx)
        ctx.check_tenant()
        sections.append(_plan_entry(section, entry["version"], plan))
    carried = {entry["section"] for entry in _contributed(manifest)}
    omitted = {
        e["section"]: e
        for e in manifest.get("omitted") or []
        if isinstance(e, dict) and isinstance(e.get("section"), str)
    }
    return {
        "sections": sections,
        "denied": denied,
        "skipped": [
            {"section": entry["section"], "version": entry.get("version")}
            for entry in _contributed(manifest)
            if registry.get(entry["section"]) is None
        ],
        "absent": [
            {"section": section.name, "label_key": section.label_key}
            | (_omitted(omitted[section.name]) if section.name in omitted else {})
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
    access: SectionAccess = SYSTEM,
    denied: frozenset[str] = frozenset(),
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Apply every known section the bundle carries, after pagebuilder's part.

    ``({section: {"counts": ..., "applied": ...}}, denied entries)``. A section
    named in *denied* (left out when the restore was staged) stays out, and one
    *access* may not apply now is skipped too: permissions change between
    staging and approval. Nothing commits here; a section that raises aborts
    the caller's whole transaction.
    """
    outcome: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    known = present(manifest, registry)
    tenant = _tenant() if known else ""
    for section, entry in known:
        missing = access.missing(section, "apply")
        if missing or section.name in denied:
            skipped.append(denied_entry(section, missing or needed(section, "apply")))
            continue
        ctx = _restore_context(db, section, entry, bundle_dir, name_to_url, tenant)
        result = await section.apply(ctx)
        ctx.check_tenant()
        outcome[section.name] = {"counts": dict(result.counts), "applied": dict(result.applied)}
    await db.flush()
    return outcome, skipped
