# Content Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give pagebuilder a Content › Import / Export admin section where the whole site can be snapshotted, downloaded and uploaded as a `.zip`, and restored only after an approval gate — with every restore itself reversible.

**Architecture:** A new `pagebuilder/snapshots/` package. Everything in the store is a *snapshot* row (`manual`, `upload`, or `pre_restore`); a restore stages a *pending import* pointing at one, whose computed *plan* an approver reads before applying. Media bytes are content-addressed by sha256 and shared across snapshots; content documents are JSON files under `snapshot_root`. Host-local foreign keys (`Page.parent_id`, `PageRedirect.page_id`) serialise as slugs and are resolved in a second pass on apply.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy async, Alembic, pytest + pytest-asyncio, React 19 + Inertia.js, shadcn/ui via `@simple-module-py/ui`, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-28-content-snapshots-design.md`

## Global Constraints

- **300-line cap** on every `.py` / `.ts` / `.tsx`, `modules/` included — enforced by `scripts/check_file_size.py`. This is why the subsystem is eight small files rather than one.
- **Migrations live in `host/migrations/versions/`, never in a module.** Generate with `make migration msg="..."`; never hand-write the revision id.
- **Nothing new under `pagebuilder/pages/`** that is not a real Inertia page — `import.meta.glob` turns any stray `.tsx` there into a registered page. Extractions go to `components/` or `hooks/`.
- **No `==` dependency pins** in a published module; framework deps stay as ranges (`simple_module_core>=0.0.25,<0.1`).
- **Versions are lockstep**; only `scripts/bump_version.py` edits them. Do not touch any version field.
- **No new cross-module Python dependency.** `pagebuilder` must not import `branding`, `news`, or `canopy_atlas`. Branding is deliberately out of the bundle for this reason.
- **No i18n.** This repo's host does not wire i18n; hardcoded English TSX is the convention here. Do not add `locales/en.json`.
- **No new hardcoded string literals** where a constant is expected — `scripts/check_hardcoded_strings.py` runs in `make lint`.
- **Run tests from the repo root** (`make test-py`); a bare root `pytest` does not collect module tests correctly.
- **Format version** is `1`, declared once in `snapshots/format.py` as `FORMAT_VERSION`.

---

### Task 1: Bundle format constants and the content-addressed blob store

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/__init__.py`
- Create: `modules/pagebuilder/pagebuilder/snapshots/format.py`
- Create: `modules/pagebuilder/pagebuilder/snapshots/blobs.py`
- Modify: `modules/pagebuilder/pagebuilder/settings.py`
- Test: `modules/pagebuilder/tests/test_snapshot_blobs.py`

**Interfaces:**
- Consumes: `pagebuilder.media_files.resolve_media_root` (path anchoring).
- Produces:
  - `FORMAT_VERSION: int = 1`
  - `MANIFEST_NAME`, `LAYOUT_NAME`, `REDIRECTS_NAME`, `PAGES_DIR`, `MEDIA_DIR`, `MEDIA_INDEX_NAME`, `BLOBS_DIR` — bundle path constants
  - `ASSET_SCHEME: str = "asset://"`
  - `class BlobStore: __init__(self, root: Path)`, `put(self, data: bytes) -> str` (returns sha256), `get(self, sha256: str) -> bytes`, `path_for(self, sha256: str) -> Path`, `exists(self, sha256: str) -> bool`, `delete_unreferenced(self, keep: set[str]) -> int`
  - `PagebuilderSettings.snapshot_root: Path`, `PagebuilderSettings.snapshot_max_upload_bytes: int`

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_blobs.py
from pagebuilder.snapshots.blobs import BlobStore


def test_put_is_content_addressed_and_idempotent(tmp_path):
    store = BlobStore(tmp_path)
    first = store.put(b"hello")
    second = store.put(b"hello")
    assert first == second
    assert store.get(first) == b"hello"
    # One file on disk, not two.
    assert len(list(store.path_for(first).parent.iterdir())) == 1


def test_delete_unreferenced_keeps_what_is_still_used(tmp_path):
    store = BlobStore(tmp_path)
    kept = store.put(b"kept")
    dropped = store.put(b"dropped")
    removed = store.delete_unreferenced(keep={kept})
    assert removed == 1
    assert store.exists(kept)
    assert not store.exists(dropped)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_blobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pagebuilder.snapshots'`

- [ ] **Step 3: Write `format.py`**

```python
"""The snapshot bundle's on-disk shape, named once.

A bundle is the same tree whether it is a directory under ``snapshot_root``
or the inside of a ``.zip`` — the only difference is that the zip carries the
media bytes under ``BLOBS_DIR`` while the server-side copy references the
shared blob store instead.
"""

from __future__ import annotations

FORMAT_VERSION = 1
"""Bumped only for a change that an older reader would misinterpret.

Checked on upload and again on restore: an unknown version is refused with a
clear message rather than partially understood.
"""

MANIFEST_NAME = "manifest.json"
LAYOUT_NAME = "layout.json"
REDIRECTS_NAME = "redirects.json"
PAGES_DIR = "pages"
MEDIA_DIR = "media"
MEDIA_INDEX_NAME = "index.json"
BLOBS_DIR = "blobs"

ASSET_SCHEME = "asset://"
"""Sentinel standing in for a media URL inside bundled content.

Media URLs embed a host-local UUID filename, so serialising them verbatim
would produce a bundle whose images 404 anywhere else.
"""
```

- [ ] **Step 4: Write `blobs.py`**

```python
"""Content-addressed storage for the bytes a snapshot carries.

Blobs are keyed by sha256 and shared by every snapshot containing them, so
ten snapshots of a site whose photographs have not changed cost one copy of
the photographs. Without that, each snapshot of a real site would duplicate
its whole media library and the feature would be unusable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, sha256: str) -> Path:
        return self.root / sha256

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.path_for(digest)
        if not target.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            # Write via a temp name then rename: a reader must never observe a
            # half-written blob under a name that promises those exact bytes.
            tmp = target.with_suffix(".partial")
            tmp.write_bytes(data)
            tmp.replace(target)
        return digest

    def get(self, sha256: str) -> bytes:
        return self.path_for(sha256).read_bytes()

    def delete_unreferenced(self, keep: set[str]) -> int:
        """Drop every blob no surviving snapshot still names. Returns the count."""
        if not self.root.is_dir():
            return 0
        removed = 0
        for path in self.root.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink()
                removed += 1
        return removed
```

- [ ] **Step 5: Add the two settings**

Append to `PagebuilderSettings` in `modules/pagebuilder/pagebuilder/settings.py`:

```python
    snapshot_root: Path = Path("var/pagebuilder/snapshots")
    """Filesystem directory holding content snapshots and their blobs.

    Anchored to the project root exactly like ``media_root`` — a
    cwd-relative default is what made two differently-launched processes
    read and write different media directories against one database
    (issue #14).
    """

    snapshot_max_upload_bytes: int = 200 * 1024 * 1024
    """Reject uploaded bundles larger than this (default 200 MB)."""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_blobs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots modules/pagebuilder/pagebuilder/settings.py modules/pagebuilder/tests/test_snapshot_blobs.py
git commit -m "feat(pagebuilder): bundle format constants and content-addressed blob store"
```

---

### Task 2: Asset sentinel rewriting

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/assets.py`
- Test: `modules/pagebuilder/tests/test_snapshot_assets.py`

**Interfaces:**
- Consumes: `ASSET_SCHEME` from Task 1.
- Produces:
  - `to_sentinels(node: Any, url_to_name: dict[str, str]) -> Any`
  - `from_sentinels(node: Any, name_to_url: dict[str, str]) -> Any`
  - `collect_sentinels(node: Any) -> set[str]`
  - `bundle_names(assets: list[tuple[int, str]]) -> dict[int, str]` — media id + original_filename, ordered by id, returns id → collision-free bundle name

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_assets.py
from pagebuilder.snapshots.assets import (
    bundle_names,
    collect_sentinels,
    from_sentinels,
    to_sentinels,
)

DOC = {
    "content": [
        {"type": "Image", "props": {"src": "/media/pagebuilder/abc123.jpg"}},
        {"type": "Logo", "props": {"src": "/canopy-atlas/static/gca/logo.svg"}},
        {"type": "Link", "props": {"href": "/gca/contact"}},
    ]
}


def test_to_sentinels_only_rewrites_known_media_urls():
    out = to_sentinels(DOC, {"/media/pagebuilder/abc123.jpg": "hero.jpg"})
    props = [b["props"] for b in out["content"]]
    assert props[0]["src"] == "asset://hero.jpg"
    # A module static mount and an in-site link are not media; both survive.
    assert props[1]["src"] == "/canopy-atlas/static/gca/logo.svg"
    assert props[2]["href"] == "/gca/contact"


def test_round_trip_restores_the_live_url():
    sentinels = to_sentinels(DOC, {"/media/pagebuilder/abc123.jpg": "hero.jpg"})
    back = from_sentinels(sentinels, {"hero.jpg": "/media/pagebuilder/zzz999.jpg"})
    assert back["content"][0]["props"]["src"] == "/media/pagebuilder/zzz999.jpg"


def test_unknown_sentinel_is_left_alone_for_the_caller_to_reject():
    back = from_sentinels({"src": "asset://missing.jpg"}, {})
    assert back["src"] == "asset://missing.jpg"
    assert collect_sentinels(back) == {"missing.jpg"}


def test_bundle_names_disambiguate_duplicates_stably():
    # Two different uploads can share an original_filename; the bundle name
    # is what makes them addressable, so it must be unique and stable.
    assert bundle_names([(1, "hero.jpg"), (5, "hero.jpg"), (9, "other.png")]) == {
        1: "hero.jpg",
        5: "hero~2.jpg",
        9: "other.png",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_assets.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `assets.py`**

```python
"""Translating media URLs to and from the portable ``asset://`` sentinel.

A media URL is ``{media_url_prefix}/{filename}`` where the filename is a UUID
assigned at upload — host-local by construction. Capture therefore replaces
every such URL with ``asset://<bundle name>`` and restore puts back whatever
URL the file was given on *this* host.

This is the inverse of ``canopy_atlas.seed.uploads.rewrite_asset_paths``,
generalised and made bidirectional. Only URLs that resolve to a row in the
media library are rewritten: the mapping is built from the media table rather
than guessed from string shape, so module static mounts
(``/canopy-atlas/static/...``), external URLs and in-site links pass through.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pagebuilder.snapshots.format import ASSET_SCHEME


def to_sentinels(node: Any, url_to_name: dict[str, str]) -> Any:
    """Replace known media URLs with ``asset://`` sentinels."""
    if isinstance(node, dict):
        return {k: to_sentinels(v, url_to_name) for k, v in node.items()}
    if isinstance(node, list):
        return [to_sentinels(v, url_to_name) for v in node]
    if isinstance(node, str) and node in url_to_name:
        return f"{ASSET_SCHEME}{url_to_name[node]}"
    return node


def from_sentinels(node: Any, name_to_url: dict[str, str]) -> Any:
    """Resolve ``asset://`` sentinels back to live URLs.

    An unresolvable sentinel is left verbatim rather than blanked: the
    validator reports it as a malformed bundle, and silently emitting an
    empty ``src`` would turn that into an invisible broken image instead.
    """
    if isinstance(node, dict):
        return {k: from_sentinels(v, name_to_url) for k, v in node.items()}
    if isinstance(node, list):
        return [from_sentinels(v, name_to_url) for v in node]
    if isinstance(node, str) and node.startswith(ASSET_SCHEME):
        return name_to_url.get(node[len(ASSET_SCHEME) :], node)
    return node


def collect_sentinels(node: Any) -> set[str]:
    """Every bundle name referenced by ``asset://`` sentinels in *node*."""
    found: set[str] = set()
    if isinstance(node, dict):
        for value in node.values():
            found |= collect_sentinels(value)
    elif isinstance(node, list):
        for value in node:
            found |= collect_sentinels(value)
    elif isinstance(node, str) and node.startswith(ASSET_SCHEME):
        found.add(node[len(ASSET_SCHEME) :])
    return found


def bundle_names(assets: list[tuple[int, str]]) -> dict[int, str]:
    """Assign each media id a collision-free name to carry in the bundle.

    ``original_filename`` is a label, not a key — two different uploads can
    share one. Ordering by media id keeps the ``~2`` suffixes identical across
    repeated captures, which is what makes the round-trip test meaningful.
    """
    taken: set[str] = set()
    names: dict[int, str] = {}
    for asset_id, original in sorted(assets):
        candidate = original
        if candidate in taken:
            stem = PurePosixPath(original).stem
            suffix = PurePosixPath(original).suffix
            counter = 2
            while candidate in taken:
                candidate = f"{stem}~{counter}{suffix}"
                counter += 1
        taken.add(candidate)
        names[asset_id] = candidate
    return names
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_assets.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/assets.py modules/pagebuilder/tests/test_snapshot_assets.py
git commit -m "feat(pagebuilder): asset:// sentinel rewriting for portable bundles"
```

---

### Task 3: Tables and migration

**Files:**
- Create: `modules/pagebuilder/pagebuilder/models/_snapshot.py`
- Modify: `modules/pagebuilder/pagebuilder/models/__init__.py`
- Create: `host/migrations/versions/<generated>_add_pagebuilder_snapshots.py`
- Test: `modules/pagebuilder/tests/test_snapshot_models.py`

**Interfaces:**
- Consumes: `pagebuilder.models._base.Base`, `simple_module_db.mixins.AuditMixin`.
- Produces: `SnapshotSource` (enum: `MANUAL`, `UPLOAD`, `PRE_RESTORE`), `ImportStatus` (enum: `PENDING`, `APPROVED`, `REJECTED`), `ContentSnapshot`, `SnapshotMedia`, `PendingImport` — all re-exported from `pagebuilder.models`.

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_models.py
from pagebuilder.models import (
    ContentSnapshot,
    ImportStatus,
    PendingImport,
    SnapshotMedia,
    SnapshotSource,
)


def test_tables_are_registered_under_the_module_prefix():
    assert ContentSnapshot.__tablename__ == "pagebuilder_snapshots"
    assert SnapshotMedia.__tablename__ == "pagebuilder_snapshot_media"
    assert PendingImport.__tablename__ == "pagebuilder_pending_imports"


def test_enum_values_are_the_wire_format():
    assert SnapshotSource.PRE_RESTORE.value == "pre_restore"
    assert ImportStatus.PENDING.value == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ContentSnapshot'`

- [ ] **Step 3: Write `models/_snapshot.py`**

```python
"""Snapshots of the whole site, and the approval gate in front of restoring one."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from pagebuilder.models._base import Base

SNAPSHOT_TABLE = "pagebuilder_snapshots"


class SnapshotSource(str, enum.Enum):  # noqa: UP042 — matches PageStatus
    """Where a snapshot came from.

    One store rather than three: *upload a bundle from prod* and *roll back to
    yesterday* differ only in this column, which is what keeps restore a
    single code path.
    """

    MANUAL = "manual"
    UPLOAD = "upload"
    PRE_RESTORE = "pre_restore"


class ImportStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContentSnapshot(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """One captured state of the site's pagebuilder content.

    The documents live as JSON files under ``snapshot_root``; this row holds
    only what the listing renders, so drawing the screen never opens a file.
    """

    __tablename__ = SNAPSHOT_TABLE

    id: int | None = Field(default=None, primary_key=True)
    note: str | None = Field(default=None, max_length=2000)
    source: SnapshotSource = Field(
        default=SnapshotSource.MANUAL,
        sa_column=Column(
            SAEnum(SnapshotSource, name="pagebuilder_snapshot_source"),
            nullable=False,
            index=True,
        ),
    )
    format_version: int = Field(default=1)
    manifest: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    size_bytes: int = Field(default=0)


class SnapshotMedia(Base, table=True):  # ty: ignore[unsupported-base]
    """A blob this snapshot references.

    Reference-counted deletion reads this table alone — dropping a snapshot
    must never mean opening every other snapshot's index to find out which
    bytes are still spoken for.
    """

    __tablename__ = "pagebuilder_snapshot_media"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key=f"{SNAPSHOT_TABLE}.id", index=True, ondelete="CASCADE"
    )
    sha256: str = Field(max_length=64, index=True)
    bundle_name: str = Field(max_length=300)
    original_filename: str = Field(max_length=300)
    content_type: str = Field(max_length=120)
    folder: str | None = Field(default=None, max_length=300)


class PendingImport(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A staged restore waiting on an approver.

    At most one row is ``PENDING`` at a time: a plan computed against content
    that has since changed misrepresents what applying would do.
    """

    __tablename__ = "pagebuilder_pending_imports"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key=f"{SNAPSHOT_TABLE}.id", index=True, ondelete="CASCADE"
    )
    plan: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    status: ImportStatus = Field(
        default=ImportStatus.PENDING,
        sa_column=Column(
            SAEnum(ImportStatus, name="pagebuilder_import_status"),
            nullable=False,
            index=True,
        ),
    )
    note: str | None = Field(default=None, max_length=2000)
    decided_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    decided_by: str | None = Field(default=None, max_length=200)
```

- [ ] **Step 4: Re-export from `models/__init__.py`**

Add the import and the `__all__` entries, keeping both alphabetical:

```python
from pagebuilder.models._snapshot import (
    ContentSnapshot,
    ImportStatus,
    PendingImport,
    SnapshotMedia,
    SnapshotSource,
)
```

`__all__` gains `"ContentSnapshot"`, `"ImportStatus"`, `"PendingImport"`, `"SnapshotMedia"`, `"SnapshotSource"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Generate the migration**

Run from the repo root: `make migration msg="add pagebuilder content snapshots"`

Then open the generated file in `host/migrations/versions/` and confirm it creates exactly the three tables plus their indexes and the two enum types. Do not edit the revision ids.

- [ ] **Step 7: Apply and verify**

Run: `make migrate`
Expected: completes without error.

- [ ] **Step 8: Commit**

```bash
git add modules/pagebuilder/pagebuilder/models host/migrations/versions modules/pagebuilder/tests/test_snapshot_models.py
git commit -m "feat(pagebuilder): snapshot, snapshot-media and pending-import tables"
```

---

### Task 4: Serialising a page to and from the bundle

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/pages.py`
- Test: `modules/pagebuilder/tests/test_snapshot_page_payload.py`

**Interfaces:**
- Produces:
  - `PAGE_FIELDS: tuple[str, ...]` — the authored columns carried in a bundle
  - `page_to_payload(page: Page, parent_slug: str | None) -> dict[str, Any]`
  - `apply_payload(page: Page, payload: dict[str, Any]) -> None` — sets every field except `parent_id`, which the second pass owns

Serialising is its own file because the field list is the part most likely to drift as `Page` grows, and a reviewer should be able to see it whole.

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_page_payload.py
from datetime import UTC, datetime

from pagebuilder.models import Page, PageStatus
from pagebuilder.snapshots.pages import apply_payload, page_to_payload


def _page() -> Page:
    return Page(
        slug="about",
        title="About",
        status=PageStatus.PUBLISHED,
        draft_data={"content": [1]},
        published_data={"content": [2]},
        meta_title="About us",
        index_in_search=False,
        is_template=False,
        show_in_header_nav=True,
        publish_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_payload_carries_every_authored_field_and_the_parent_slug():
    payload = page_to_payload(_page(), parent_slug="home")
    assert payload["slug"] == "about"
    assert payload["status"] == "published"
    assert payload["published_data"] == {"content": [2]}
    assert payload["parent_slug"] == "home"
    assert payload["meta_title"] == "About us"
    assert payload["index_in_search"] is False
    assert payload["show_in_header_nav"] is True
    assert payload["publish_at"] == "2026-01-01T00:00:00+00:00"


def test_apply_payload_round_trips_without_touching_parent_id():
    payload = page_to_payload(_page(), parent_slug="home")
    target = Page(slug="about", title="stale")
    target.parent_id = 42
    apply_payload(target, payload)
    assert target.title == "About"
    assert target.status is PageStatus.PUBLISHED
    assert target.publish_at == datetime(2026, 1, 1, tzinfo=UTC)
    # The second pass owns parenting; pass one must not clear it.
    assert target.parent_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_page_payload.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `pages.py`**

```python
"""Turning a ``Page`` row into bundle JSON and back.

Kept apart from capture and apply because ``PAGE_FIELDS`` is the part most
likely to drift as ``Page`` grows a column — a reviewer should be able to see
the whole list at once and notice what is missing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pagebuilder.models import Page, PageStatus

PAGE_FIELDS: tuple[str, ...] = (
    "title",
    "meta_title",
    "meta_description",
    "og_image",
    "canonical_url",
    "index_in_search",
    "json_ld",
    "show_in_header_nav",
    "show_in_footer",
    "is_template",
    "draft_data",
    "published_data",
)
"""Authored columns carried verbatim.

Excluded on purpose: ``id`` and ``parent_id`` (host-local), ``deleted_at``
(trashed pages are never captured), ``rejection_note`` (a workflow artefact,
not content), and the ``AuditMixin`` timestamps, which describe this host's
history rather than the content's.
"""

_DATETIME_FIELDS: tuple[str, ...] = ("publish_at", "unpublish_at")


def page_to_payload(page: Page, parent_slug: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"slug": page.slug, "parent_slug": parent_slug}
    payload["status"] = page.status.value
    for field in PAGE_FIELDS:
        payload[field] = getattr(page, field)
    for field in _DATETIME_FIELDS:
        value: datetime | None = getattr(page, field)
        payload[field] = value.isoformat() if value is not None else None
    return payload


def apply_payload(page: Page, payload: dict[str, Any]) -> None:
    """Write *payload* onto *page*, leaving ``parent_id`` to the second pass."""
    page.status = PageStatus(payload["status"])
    for field in PAGE_FIELDS:
        if field in payload:
            setattr(page, field, payload[field])
    for field in _DATETIME_FIELDS:
        raw = payload.get(field)
        setattr(page, field, datetime.fromisoformat(raw) if raw else None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_page_payload.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/pages.py modules/pagebuilder/tests/test_snapshot_page_payload.py
git commit -m "feat(pagebuilder): page payload serialisation for snapshots"
```

---

### Task 5: Capture — live content to a bundle directory

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/capture.py`
- Test: `modules/pagebuilder/tests/test_snapshot_capture.py`

**Interfaces:**
- Consumes: `BlobStore`, `bundle_names`, `to_sentinels`, `page_to_payload`, format constants, `NOT_TRASHED`.
- Produces: `async def capture(db, settings, dest: Path, blobs: BlobStore) -> CaptureResult` where `CaptureResult` is a dataclass with `manifest: dict`, `media: list[SnapshotMedia]`, `size_bytes: int`.

Capture reads through the ORM in-process — never over HTTP back into the app.

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_capture.py
import json

import pytest
from conftest import PNG_BYTES  # noqa: F401 — harness fixture module


@pytest.mark.anyio
async def test_capture_skips_trashed_pages_and_keeps_templates(authed_client):
    from conftest import create_draft

    await create_draft(authed_client, slug="live", title="Live")
    binned = await create_draft(authed_client, slug="binned", title="Binned")
    await authed_client.delete(f"/api/pagebuilder/pages/{binned['id']}")

    response = await authed_client.post(
        "/api/pagebuilder/snapshots", json={"note": "first"}
    )
    assert response.status_code == 201, response.text
    slugs = {entry["slug"] for entry in response.json()["manifest"]["pages"]}
    assert "live" in slugs
    assert "binned" not in slugs


@pytest.mark.anyio
async def test_capture_records_parent_as_a_slug(authed_client):
    from conftest import create_draft

    parent = await create_draft(authed_client, slug="parent", title="Parent")
    child = await create_draft(authed_client, slug="child", title="Child")
    await authed_client.put(
        f"/api/pagebuilder/pages/{child['id']}", json={"parent_id": parent["id"]}
    )

    response = await authed_client.post("/api/pagebuilder/snapshots", json={})
    assert response.status_code == 201, response.text
    entry = next(
        e for e in response.json()["manifest"]["pages"] if e["slug"] == "child"
    )
    assert entry["parent_slug"] == "parent"
```

Note: these are integration tests through the API, which does not exist until Task 9. Write them now and mark the module `pytest.mark.skip(reason="API arrives in Task 9")` at the top; remove the skip in Task 9 Step 6. The unit-level capture behaviour is covered below.

- [ ] **Step 2: Write the unit test that runs today**

```python
# append to modules/pagebuilder/tests/test_snapshot_capture.py
@pytest.mark.anyio
async def test_capture_writes_the_bundle_tree(tmp_path, snapshot_db):
    """``snapshot_db`` is the fixture added in Step 3 below."""
    from pagebuilder.snapshots.blobs import BlobStore
    from pagebuilder.snapshots.capture import capture

    dest = tmp_path / "bundle"
    result = await capture(
        snapshot_db.session, snapshot_db.settings, dest, BlobStore(tmp_path / "blobs")
    )
    assert (dest / "manifest.json").is_file()
    assert (dest / "layout.json").is_file()
    assert (dest / "redirects.json").is_file()
    assert (dest / "pages").is_dir()
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["format_version"] == 1
    assert result.manifest == manifest
```

- [ ] **Step 3: Add the `snapshot_db` fixture**

Append to `modules/pagebuilder/tests/conftest.py` — a bare session + settings pair for unit-testing the snapshot layer without building a whole app:

```python
@pytest.fixture
async def snapshot_db(tmp_path):
    """An empty pagebuilder schema plus settings rooted in ``tmp_path``.

    The snapshot layer talks to the ORM directly, so its unit tests want a
    session rather than the full ASGI harness the API tests use.
    """
    db_state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(db_state)
    async with db_state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        snapshot_root=tmp_path / "snapshots",
    )
    async with db_state.session_factory() as session:
        yield SimpleNamespace(session=session, settings=settings)
    await db_state.engine.dispose()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_capture.py -v`
Expected: FAIL with `ModuleNotFoundError: pagebuilder.snapshots.capture`

- [ ] **Step 5: Write `capture.py`**

Structure (keep under 300 lines):

```python
"""Reading the live site into a bundle directory.

Runs in-process against the ORM. Everything host-local is translated on the
way out: media URLs become ``asset://`` sentinels, ``Page.parent_id`` becomes
a slug, and ``PageRedirect.page_id`` becomes its target's slug. Trashed pages
are filtered out by the module's own ``NOT_TRASHED``, so a snapshot holds
exactly what the site serves.
"""
```

- `_media_maps(db, settings)` → `(url_to_name, media_rows)` using `bundle_names` over `(id, original_filename)` ordered by id, and `MediaService.url_for` for the URL side.
- `_capture_pages(db, dest, url_to_name)` → writes `pages/<slug>.json` per page (filtered by `NOT_TRASHED`), resolving `parent_id` through a `{id: slug}` map built in the same query, and returns the manifest page list `[{slug, title, status, parent_slug}]`.
- `_capture_layout(db, dest, url_to_name)` → `layout.json` from `LayoutService.get()`.
- `_capture_redirects(db, dest)` → `redirects.json` as `[{from_slug, to_slug}]`, joining `PageRedirect.page_id` to the page's slug.
- `_capture_media(dest, blobs, media_rows)` → copies each asset's bytes into the blob store, writes `media/index.json`.
- `capture(...)` orchestrates, writes `manifest.json` last (so a half-written bundle has no manifest and is self-evidently incomplete), and returns `CaptureResult`.

- [ ] **Step 6: Run tests to verify the unit test passes**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_capture.py -v -k bundle_tree`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/capture.py modules/pagebuilder/tests/test_snapshot_capture.py modules/pagebuilder/tests/conftest.py
git commit -m "feat(pagebuilder): capture live content into a bundle directory"
```

---

### Task 6: Archive — zip in, zip out, and validation

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/archive.py`
- Test: `modules/pagebuilder/tests/test_snapshot_archive.py`

**Interfaces:**
- Produces:
  - `class BundleError(Exception)` — every rejection reason for a malformed bundle
  - `write_zip(bundle_dir: Path, blobs: BlobStore, media: list[SnapshotMedia], target: Path) -> int` (returns bytes written)
  - `read_zip(data: bytes, dest: Path, blobs: BlobStore) -> tuple[dict, list[dict]]` — extracts, validates, stores blobs, returns `(manifest, media_index_entries)`

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_archive.py
import io
import json
import zipfile

import pytest

from pagebuilder.snapshots.archive import BundleError, read_zip
from pagebuilder.snapshots.blobs import BlobStore


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_unknown_format_version_is_refused(tmp_path):
    data = _zip({"manifest.json": json.dumps({"format_version": 99}).encode()})
    with pytest.raises(BundleError, match="format version"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_missing_manifest_is_refused(tmp_path):
    with pytest.raises(BundleError, match="manifest"):
        read_zip(_zip({"pages/a.json": b"{}"}), tmp_path / "out", BlobStore(tmp_path))


def test_path_traversal_entry_is_refused(tmp_path):
    # A zip is attacker-controlled input the moment it is uploaded.
    data = _zip(
        {
            "manifest.json": json.dumps({"format_version": 1}).encode(),
            "../escape.json": b"{}",
        }
    )
    with pytest.raises(BundleError, match="path"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_archive.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `archive.py`**

Requirements the tests pin down, plus what a reviewer should expect:

- Every entry name is normalised and rejected if it escapes the destination (`..`, absolute paths, drive letters) — an uploaded zip is untrusted input.
- `manifest.json` must exist and its `format_version` must equal `FORMAT_VERSION`.
- Every `media/blobs/<sha256>` entry is verified: the stored bytes must actually hash to the name they arrived under, otherwise the bundle is corrupt.
- Every sentinel found across `pages/*.json` and `layout.json` must appear in `media/index.json`; a missing one raises `BundleError` at upload rather than surfacing as a broken image after apply.
- Blobs go into the shared `BlobStore` on the way in; the extracted tree keeps only the documents.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_archive.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/archive.py modules/pagebuilder/tests/test_snapshot_archive.py
git commit -m "feat(pagebuilder): snapshot zip read/write with bundle validation"
```

---

### Task 7: The restore plan

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/plan.py`
- Test: `modules/pagebuilder/tests/test_snapshot_plan.py`

**Interfaces:**
- Consumes: `pagebuilder.diff.revision_diff`-style block pairing (reuse the helpers, do not duplicate them).
- Produces: `async def build_plan(db, bundle_dir: Path, media_index: dict) -> dict` returning
  `{"pages": {"new": [...], "overwritten": [...], "unchanged": [...], "untouched": [...]}, "layout": {...}, "redirects": {...}, "media": {"new": int, "existing": int}}`

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_plan.py
import pytest


@pytest.mark.anyio
async def test_plan_classifies_pages(snapshot_db, tmp_path):
    from pagebuilder.snapshots.plan import build_plan

    # Bundle holds "kept" (identical), "changed", "fresh"; the site also has
    # "extra", which the bundle does not mention.
    bundle = _write_bundle(tmp_path, slugs=["kept", "changed", "fresh"])
    await _seed_site(snapshot_db.session, {"kept": "same", "changed": "old", "extra": "x"})

    plan = await build_plan(snapshot_db.session, bundle, {})
    assert [p["slug"] for p in plan["pages"]["new"]] == ["fresh"]
    assert [p["slug"] for p in plan["pages"]["overwritten"]] == ["changed"]
    assert [p["slug"] for p in plan["pages"]["unchanged"]] == ["kept"]
    assert [p["slug"] for p in plan["pages"]["untouched"]] == ["extra"]
```

Write `_write_bundle` and `_seed_site` as module-level helpers in the test file — they build a minimal bundle directory and insert `Page` rows respectively.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_plan.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `plan.py`**

- Compare each bundled page against the live row by `draft_data` + the `PAGE_FIELDS` values; equal means `unchanged`.
- For `overwritten`, attach a block-level summary using the same `props.id` pairing `diff.py` already implements — import its helpers rather than re-deriving them.
- `untouched` lists live, non-trashed slugs absent from the bundle. Restore never deletes; the plan is where the approver learns that.
- Redirects: `added` / `removed`, and `dropped` for any whose `to_slug` resolves to nothing in bundle-or-site.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_plan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/plan.py modules/pagebuilder/tests/test_snapshot_plan.py
git commit -m "feat(pagebuilder): compute the restore plan an approver reads"
```

---

### Task 8: Apply — the two-pass atomic restore

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/apply.py`
- Test: `modules/pagebuilder/tests/test_snapshot_apply.py`

**Interfaces:**
- Produces: `async def apply_bundle(db, settings, bundle_dir: Path, blobs: BlobStore, media_index: dict) -> dict` returning counts applied.

- [ ] **Step 1: Write the failing tests — round-trip fidelity is the load-bearing one**

```python
# modules/pagebuilder/tests/test_snapshot_apply.py
import pytest


@pytest.mark.anyio
async def test_round_trip_is_byte_identical(snapshot_db, tmp_path):
    """capture -> wipe -> apply -> capture must reproduce the same bundle."""
    from pagebuilder.snapshots.apply import apply_bundle
    from pagebuilder.snapshots.blobs import BlobStore
    from pagebuilder.snapshots.capture import capture

    blobs = BlobStore(tmp_path / "blobs")
    await _seed_rich_site(snapshot_db.session)  # pages, parent, redirect, media

    first = tmp_path / "one"
    await capture(snapshot_db.session, snapshot_db.settings, first, blobs)

    await _wipe(snapshot_db.session)
    await apply_bundle(
        snapshot_db.session, snapshot_db.settings, first, blobs, _index(first)
    )

    second = tmp_path / "two"
    await capture(snapshot_db.session, snapshot_db.settings, second, blobs)

    assert _tree(first) == _tree(second)


@pytest.mark.anyio
async def test_parent_resolves_even_when_it_sorts_after_the_child(snapshot_db, tmp_path):
    # "zeta" is the parent of "alpha"; a single-pass restore would fail here.
    ...


@pytest.mark.anyio
async def test_unresolvable_parent_becomes_none_rather_than_failing(snapshot_db, tmp_path):
    ...
```

Write `_tree` to return `{relative path: parsed json}` for every file in a bundle directory, so a mismatch reports which document differs rather than "bytes differ".

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_apply.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `apply.py`**

Order matters and is the whole point of the file:

1. **Media first** — upsert by `original_filename` (the rule the GCA seed already uses, so re-running is idempotent), pushing blob bytes through the normal upload path so thumbnails regenerate against current settings. Build `name_to_url` as you go.
2. **Pages, pass one** — upsert by slug, `apply_payload` with `from_sentinels(…, name_to_url)` applied to `draft_data` / `published_data`. Never touch `parent_id` here.
3. **Pages, pass two** — resolve every `parent_slug` against the now-complete `{slug: id}` map; an unresolvable one sets `None`, matching `ondelete="SET NULL"`.
4. **Redirects** — delete and rebuild from the bundle; drop any whose `to_slug` is unresolvable.
5. **Layout** — `LayoutService.update` with sentinel-resolved header/footer.

The caller owns the transaction; `apply_bundle` must not commit, so a failure anywhere rolls the whole thing back.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_apply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pagebuilder/pagebuilder/snapshots/apply.py modules/pagebuilder/tests/test_snapshot_apply.py
git commit -m "feat(pagebuilder): two-pass atomic restore with slug-resolved parents"
```

---

### Task 9: Service orchestration and the JSON API

**Files:**
- Create: `modules/pagebuilder/pagebuilder/snapshots/service.py`
- Create: `modules/pagebuilder/pagebuilder/endpoints/api/snapshots.py`
- Modify: `modules/pagebuilder/pagebuilder/endpoints/api/__init__.py`
- Modify: `modules/pagebuilder/pagebuilder/contracts/schemas.py`
- Modify: `modules/pagebuilder/pagebuilder/deps.py`
- Test: `modules/pagebuilder/tests/test_snapshots_api.py`

**Interfaces:**
- Produces: `SnapshotService` with `list()`, `take(note)`, `download(id)`, `delete(id)`, `upload(filename, data)`, `request_restore(id)`, `pending()`, `approve(id)`, `reject(id, note)`; and `get_snapshot_service` in `deps.py`.
- Endpoints exactly as the spec's API surface section lists.

- [ ] **Step 1: Write the failing tests**

```python
# modules/pagebuilder/tests/test_snapshots_api.py
import pytest


@pytest.mark.anyio
async def test_editor_cannot_take_a_snapshot(editor_client):
    response = await editor_client.post("/api/pagebuilder/snapshots", json={})
    assert response.status_code == 403


@pytest.mark.anyio
async def test_taking_and_listing(authed_client):
    created = await authed_client.post(
        "/api/pagebuilder/snapshots", json={"note": "before rework"}
    )
    assert created.status_code == 201, created.text
    listing = await authed_client.get("/api/pagebuilder/snapshots")
    assert [s["note"] for s in listing.json()["items"]] == ["before rework"]


@pytest.mark.anyio
async def test_restore_stages_and_only_approver_applies(approver_client, editor_client):
    snapshot = (await approver_client.post("/api/pagebuilder/snapshots", json={})).json()
    staged = await approver_client.post(
        f"/api/pagebuilder/snapshots/{snapshot['id']}/restore"
    )
    assert staged.status_code == 201
    pending = (await approver_client.get("/api/pagebuilder/imports/pending")).json()
    assert pending["status"] == "pending"
    refused = await editor_client.post(
        f"/api/pagebuilder/imports/{pending['id']}/approve"
    )
    assert refused.status_code == 403


@pytest.mark.anyio
async def test_second_restore_is_refused_while_one_is_pending(approver_client):
    snapshot = (await approver_client.post("/api/pagebuilder/snapshots", json={})).json()
    await approver_client.post(f"/api/pagebuilder/snapshots/{snapshot['id']}/restore")
    again = await approver_client.post(
        f"/api/pagebuilder/snapshots/{snapshot['id']}/restore"
    )
    assert again.status_code == 409


@pytest.mark.anyio
async def test_approving_takes_a_pre_restore_snapshot_first(approver_client):
    snapshot = (await approver_client.post("/api/pagebuilder/snapshots", json={})).json()
    staged = (
        await approver_client.post(
            f"/api/pagebuilder/snapshots/{snapshot['id']}/restore"
        )
    ).json()
    await approver_client.post(f"/api/pagebuilder/imports/{staged['id']}/approve")
    listing = (await approver_client.get("/api/pagebuilder/snapshots")).json()
    assert any(s["source"] == "pre_restore" for s in listing["items"])


@pytest.mark.anyio
async def test_pending_is_null_when_idle(authed_client):
    response = await authed_client.get("/api/pagebuilder/imports/pending")
    assert response.status_code == 200
    assert response.json() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshots_api.py -v`
Expected: FAIL with 404s (routes absent)

- [ ] **Step 3: Write `service.py`**

Orchestrates the pieces from Tasks 1–8 and owns the DB rows. `approve` is the only place that takes a `pre_restore` snapshot, and it does so *before* calling `apply_bundle`. `delete` removes the snapshot directory then calls `BlobStore.delete_unreferenced` with the sha set still named by surviving `SnapshotMedia` rows.

- [ ] **Step 4: Write schemas**

Add `SnapshotRead`, `SnapshotListResponse`, `SnapshotCreateRequest`, `PendingImportRead`, `ImportDecisionRequest` to `contracts/schemas.py`.

- [ ] **Step 5: Write `endpoints/api/snapshots.py` and register it**

Every route carries `require_publish` except approve/reject, which carry `require_approve`. Register in `endpoints/api/__init__.py`:

```python
router.include_router(snapshots.router)
```

Upload enforces `snapshot_max_upload_bytes` before reading the whole body into memory.

- [ ] **Step 6: Un-skip the Task 5 integration tests**

Remove the `pytest.mark.skip` from `tests/test_snapshot_capture.py`.

- [ ] **Step 7: Run the whole module suite**

Run: `cd modules/pagebuilder && uv run pytest -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add modules/pagebuilder/pagebuilder modules/pagebuilder/tests
git commit -m "feat(pagebuilder): snapshot service and JSON API with approval gate"
```

---

### Task 10: Admin views, menu entry and the API client

**Files:**
- Modify: `modules/pagebuilder/pagebuilder/endpoints/views.py`
- Modify: `modules/pagebuilder/pagebuilder/module.py`
- Create: `modules/pagebuilder/pagebuilder/utils/snapshotsApi.ts`
- Test: `modules/pagebuilder/tests/test_snapshot_views.py`

**Interfaces:**
- Produces: `GET /pagebuilder/content` → Inertia component `ContentSnapshots`; `GET /pagebuilder/content/review` → `ContentImportReview`; menu item **Import / Export** at `order=230`.
- `snapshotsApi.ts` exports `listSnapshots`, `takeSnapshot`, `uploadBundle`, `requestRestore`, `deleteSnapshot`, `approveImport`, `rejectImport` — all built on the existing `utils/request.ts` helper so CSRF handling is not reinvented.

- [ ] **Step 1: Write the failing test**

```python
# modules/pagebuilder/tests/test_snapshot_views.py
import pytest


@pytest.mark.anyio
async def test_content_view_renders_the_inertia_component(authed_client):
    response = await authed_client.get(
        "/pagebuilder/content", headers={"X-Inertia": "true"}
    )
    assert response.status_code == 200
    assert response.json()["component"] == "ContentSnapshots"


@pytest.mark.anyio
async def test_menu_lists_import_export():
    from simple_module_core.menu import MenuRegistry
    from pagebuilder.module import PagebuilderModule

    registry = MenuRegistry()
    PagebuilderModule().register_menu_items(registry)
    labels = [item.label for item in registry.items]
    assert "Import / Export" in labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_views.py -v`
Expected: FAIL — 404 and missing label

- [ ] **Step 3: Add the view routes**

Follow the shape of `admin_trash`: the view passes the snapshot list (and, for the review route, the pending import + plan) as Inertia props so the first paint needs no client fetch.

- [ ] **Step 4: Add the menu item**

Add `_URL_CONTENT = "/pagebuilder/content"` and `_ICON_CONTENT = "package"` beside the existing constants, then a fourth `MenuItem(label="Import / Export", url=_URL_CONTENT, icon=_ICON_CONTENT, order=230, section=MenuSection.SIDEBAR, group=_MENU_GROUP)`.

- [ ] **Step 5: Write `snapshotsApi.ts`**

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd modules/pagebuilder && uv run pytest tests/test_snapshot_views.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add modules/pagebuilder/pagebuilder modules/pagebuilder/tests/test_snapshot_views.py
git commit -m "feat(pagebuilder): Import / Export admin routes, menu entry and API client"
```

---

### Task 11: The two Inertia pages

**Files:**
- Create: `modules/pagebuilder/pagebuilder/pages/ContentSnapshots.tsx`
- Create: `modules/pagebuilder/pagebuilder/pages/ContentImportReview.tsx`
- Create: `modules/pagebuilder/pagebuilder/components/snapshots/SnapshotList.tsx`
- Create: `modules/pagebuilder/pagebuilder/components/snapshots/UploadBundleDialog.tsx`
- Create: `modules/pagebuilder/pagebuilder/components/snapshots/ImportPlanSummary.tsx`
- Create: `modules/pagebuilder/pagebuilder/hooks/useSnapshots.ts`
- Test: `modules/pagebuilder/pagebuilder/components/snapshots/ImportPlanSummary.test.tsx`

**Interfaces:**
- Consumes: `snapshotsApi.ts` from Task 10, `PageShell` / `AuthenticatedLayout` / shadcn primitives from `@simple-module-py/ui`, matching `PendingReview.tsx`.

- [ ] **Step 1: Write the failing component test**

```tsx
// ImportPlanSummary.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ImportPlanSummary } from './ImportPlanSummary';

const PLAN = {
  pages: {
    new: [{ slug: 'newsroom' }],
    overwritten: [{ slug: 'home', changedBlocks: 3 }],
    unchanged: [{ slug: 'contact' }],
    untouched: [{ slug: 'legacy' }],
  },
  layout: { changed: true, header: 4, footer: 6 },
  redirects: { added: 1, removed: 0, dropped: [] },
  media: { new: 3, existing: 8 },
};

describe('ImportPlanSummary', () => {
  it('leads with how much will be overwritten', () => {
    render(<ImportPlanSummary plan={PLAN} />);
    expect(screen.getByText(/1 page will be overwritten/i)).toBeInTheDocument();
  });

  it('says plainly that untouched pages are kept, not deleted', () => {
    render(<ImportPlanSummary plan={PLAN} />);
    expect(screen.getByText(/legacy/)).toBeInTheDocument();
    expect(screen.getByText(/will not be deleted/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run from the repo root: `npx vitest run modules/pagebuilder/pagebuilder/components/snapshots/ImportPlanSummary.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Build the components**

`ImportPlanSummary` is the screen that has to earn trust: lead with the overwrite count, group by kind, and state explicitly that pages absent from the bundle are kept. `SnapshotList` shows date, author, note, a contents line and size, with Download / Restore / Delete. `UploadBundleDialog` takes a `.zip` and surfaces `BundleError` text verbatim — a rejected bundle should say *why*.

Follow the repo's existing dialog convention rather than `confirm()`: PR #23 retired every browser dialog, so use the shadcn dialog primitives as `PendingReview` and `Trash` now do.

- [ ] **Step 4: Build the two pages**

`ContentSnapshots.tsx` reads `snapshots` and `pending` from Inertia props and shows a banner linking to the review screen when one is pending. `ContentImportReview.tsx` renders `ImportPlanSummary` plus Approve & apply / Reject.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run modules/pagebuilder/pagebuilder/components/snapshots/ImportPlanSummary.test.tsx`
Expected: PASS (2 passed)

- [ ] **Step 6: Typecheck**

Run: `make typecheck`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add modules/pagebuilder/pagebuilder/pages modules/pagebuilder/pagebuilder/components/snapshots modules/pagebuilder/pagebuilder/hooks/useSnapshots.ts
git commit -m "feat(pagebuilder): Import / Export screens with plan review"
```

---

### Task 12: Documentation and full-suite verification

**Files:**
- Modify: `modules/pagebuilder/README.md`
- Modify: `CLAUDE.md` (only if a new easy-to-get-wrong rule emerged)
- Test: whole suite

- [ ] **Step 1: Document the feature in the module README**

A "Content snapshots" section: what a snapshot contains, what it deliberately does not (branding, news, trashed pages, history), the approval flow, and the two settings.

- [ ] **Step 2: Run the full Python suite**

Run: `make test-py`
Expected: all pass

- [ ] **Step 3: Run the JS suite and typecheck**

Run: `make test-js && make typecheck`
Expected: all pass

- [ ] **Step 4: Run lint**

Run: `make lint`
Expected: clean — including `check_file_size.py` (300-line cap) and `check_readmes.py`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs(pagebuilder): document content snapshots"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: bundle format → 1, 4, 6; `asset://` → 2; blob store → 1; tables/migration → 3; capture incl. trash filter and slug identity → 5; zip + validation → 6; plan → 7; two-pass apply + pre-restore → 8, 9; permissions and single-pending-import → 9; settings → 1; admin UI → 10, 11; testing → distributed, with round-trip fidelity in 8; out-of-scope items are not implemented anywhere, as intended.

**Placeholders.** Tasks 5, 6, 7, 8 and 11 describe some implementations structurally rather than as full literal code — deliberate, because those files are long and their exact bodies depend on interfaces fixed in earlier tasks. Every one of them carries its test first, so the contract is pinned even where the body is described. The `...` bodies in Task 8 Step 1 are test stubs to be filled from the named scenario, not skipped work.

**Type consistency.** `bundle_names` returns `dict[int, str]` (media id → bundle name) and is consumed that way in Task 5. `to_sentinels` takes `url_to_name`; `from_sentinels` takes `name_to_url` — deliberately different maps, checked in the Task 2 round-trip test. `apply_bundle` does not commit; the caller in Task 9 owns the transaction. `PAGE_FIELDS` excludes `parent_id`, which Task 8's pass two sets.
