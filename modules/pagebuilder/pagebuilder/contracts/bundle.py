"""Contributing a section to the content bundle (#80).

A content bundle (Import / Export) is pagebuilder's: pages, redirects, layout
and media. Another module that wants its content to travel with the site — and
to be covered by the ``pre_restore`` safety snapshot — implements
:class:`BundleSection` and registers it from its ``on_startup``::

    from pagebuilder.contracts import bundle
    bundle.register_section(app, MySection())

Pagebuilder then calls the section at four points:

* **capture** — every snapshot (manual and ``pre_restore``), after pagebuilder's
  own documents. Write files under ``ctx.dir`` only.
* **validate** — on upload, in the extraction thread, before the bundle is
  accepted. Raise ``ctx.invalid(...)`` for anything apply could not survive;
  that is a 422 and the upload is discarded.
* **plan** — when a restore is staged, and again at approval. Read-only.
  Raise ``ctx.conflict(...)`` for what cannot be applied; that is a 409 and
  nothing is written.
* **apply** — inside the approval's transaction, after pagebuilder's own part.

**Rules for a contributor.** They are what make a restore all or nothing
across modules:

* Write only through ``ctx.db``, the restore request's own session. ``flush()``
  is allowed; never ``commit()`` or ``finalize_session``, never open a session
  from a ``session_factory``, never open a nested ``begin()``.
* Do nothing outside the database (no files beyond ``ctx.dir`` at capture, no
  HTTP, no bus events). There is no commit callback in this version.
* Raise to abort. Any exception aborts the whole restore — pagebuilder's part
  rolls back too, and the import stays pending.
* Never resolve a tenant. ``ctx.tenant_id`` is the tenant pagebuilder bound
  for the request; pagebuilder checks it is still the bound one before every
  call (:meth:`check_tenant`, which a contributor may call again), and the
  framework's tenant filter keeps the contributor's ORM statements inside it.
* Contributors are applied in name order after pagebuilder and may not depend
  on one another.

Media URLs inside a contributor's documents are made portable with
``ctx.to_portable`` (the same ``asset://`` sentinels pages use) and resolved
again with ``ctx.from_portable``. A section whose documents reference media
should check them at upload with ``ctx.check_media``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from simple_module_db import current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.snapshots.match import (
    Identified,
    IdentityMatch,
    RestoreConflictError,
    match_by_identity,
)
from pagebuilder.snapshots.registry import SectionRegistry


class TenantMismatchError(RuntimeError):
    """A section was called without, or outside, the tenant it was handed."""


@dataclass(frozen=True, kw_only=True)
class _Bound:
    db: AsyncSession
    tenant_id: str
    dir: Path

    def check_tenant(self) -> None:
        """Fail closed unless the bound tenant is still ``ctx.tenant_id``."""
        bound = current_tenant_id.get()
        if not self.tenant_id or bound != self.tenant_id:
            raise TenantMismatchError(
                f"bundle section called for tenant {self.tenant_id!r} while {bound!r} is bound"
            )


@dataclass(frozen=True, kw_only=True)
class CaptureContext(_Bound):
    """``dir`` is ``<bundle>/<section name>/``, created empty."""

    to_portable: Callable[[Any], Any] = field(repr=False)
    """pagebuilder's media URL -> ``asset://`` rewrite, over any JSON value."""

    def write_json(self, relative: str, payload: Any) -> int:
        """Write *payload* under ``dir`` the way every bundle document is written."""
        from pagebuilder.snapshots.files import write_json

        return write_json(self.dir / relative, payload)


@dataclass(frozen=True)
class ValidateContext:
    """An uploaded section, extracted but not yet accepted. ``dir`` may not exist."""

    dir: Path
    version: int
    media_names: frozenset[str]

    def invalid(self, message: str) -> Exception:
        """The exception to raise for a section this host must refuse (422)."""
        from pagebuilder.snapshots.validate import BundleError

        return BundleError(message)

    def read_json(self, relative: str) -> Any:
        """Parse a document under ``dir``; bad JSON is :meth:`invalid`."""
        try:
            return json.loads((self.dir / relative).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise self.invalid(f"{self.dir.name}/{relative} is not readable JSON") from exc

    def check_media(self, node: Any, label: str) -> None:
        """Refuse *node* if it references media the bundle does not carry."""
        from pagebuilder.snapshots.assets import collect_sentinels

        missing = sorted(collect_sentinels(node) - self.media_names)
        if missing:
            raise self.invalid(
                f"{label} references media it does not contain: " + ", ".join(missing)
            )


@dataclass(frozen=True, kw_only=True)
class RestoreContext(_Bound):
    """A staged or approved restore. ``dir`` holds the section's files."""

    version: int
    """The section version the bundle was written at (one of ``readable_versions``)."""
    from_portable: Callable[[Any], Any] = field(repr=False)
    """``asset://`` -> this host's media URL, over any JSON value."""

    def conflict(self, message: str) -> Exception:
        """The exception to raise for what cannot land on this site (409)."""
        return RestoreConflictError(message)

    def read_json(self, relative: str, default: Any = None) -> Any:
        """A document under ``dir`` (already validated), or *default* if absent."""
        path = self.dir / relative
        return json.loads(path.read_text()) if path.is_file() else default


@dataclass(frozen=True)
class SectionCapture:
    counts: dict[str, int] = field(default_factory=dict)
    """Per-kind totals, written into the manifest entry (``{"articles": 42}``)."""


@dataclass(frozen=True)
class PlanItem:
    title: str
    slug: str
    locale: str | None = None
    note_key: str | None = None


@dataclass(frozen=True)
class PlanLine:
    label_key: str
    count: int
    items: list[PlanItem] = field(default_factory=list)
    tone: Literal["warning"] | None = None


@dataclass(frozen=True)
class SectionPlan:
    lines: list[PlanLine] = field(default_factory=list)
    overwrites: int = 0
    """Items this restore overwrites; added to the approval warning's total."""


@dataclass(frozen=True)
class SectionApplied:
    counts: dict[str, int] = field(default_factory=dict)
    applied: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """Identities this apply wrote, kept on the import's audit row."""


@runtime_checkable
class BundleSection(Protocol):
    name: str
    """``[a-z][a-z0-9_]*``, not one of pagebuilder's reserved names. Files live
    under ``<name>/`` in the bundle."""
    version: int
    """The section version this build writes."""
    readable_versions: frozenset[int]
    """Versions this build restores. A bundle carrying the section at any
    other version is refused (422), never partly restored."""
    required: bool
    """Written into the manifest entry: a host without this section refuses a
    required one and skips an optional one."""
    label_key: str
    count_label_keys: Mapping[str, str]

    async def capture(self, ctx: CaptureContext) -> SectionCapture: ...

    def validate(self, ctx: ValidateContext) -> None: ...

    async def plan(self, ctx: RestoreContext) -> SectionPlan: ...

    async def apply(self, ctx: RestoreContext) -> SectionApplied: ...


def register_section(app: Any, section: BundleSection) -> bool:
    """Add *section* to the app's bundle; ``False`` when pagebuilder is not mounted.

    Raises ``ValueError`` for a reserved, invalid or duplicate name, or a
    section that cannot read the version it writes.
    """
    services = getattr(app.state, "pagebuilder", None)
    registry = getattr(services, "bundle_sections", None)
    if not isinstance(registry, SectionRegistry):
        return False
    registry.register(section)
    return True


__all__ = [
    "BundleSection",
    "CaptureContext",
    "Identified",
    "IdentityMatch",
    "PlanItem",
    "PlanLine",
    "RestoreContext",
    "SectionApplied",
    "SectionCapture",
    "SectionPlan",
    "TenantMismatchError",
    "ValidateContext",
    "match_by_identity",
    "register_section",
]
