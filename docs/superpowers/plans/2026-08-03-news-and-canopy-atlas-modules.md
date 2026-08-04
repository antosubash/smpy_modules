# News and Canopy Atlas modules — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Global Canopy Atlas site out of `pagebuilder` into a
`simple_module_canopy_atlas` module, and add a `simple_module_news` module
whose articles reuse pagebuilder Pages.

**Architecture:** The design pack becomes a site-wide branding setting backed
by a new `DesignPackRegistry` in the framework, so `pagebuilder` stops shipping
one site's brand. A Puck block registry lets a module contribute editor blocks
without `pagebuilder` importing it, which is how the news feed reaches a page.
News owns only a sidecar table keyed to `pagebuilder_pages`; the article body,
slug, workflow and public URL stay with the page.

**Tech Stack:** FastAPI, SQLModel, Alembic, Inertia.js + React 19, Puck 0.19,
Tailwind v4, uv + npm workspaces, pytest, Playwright.

Spec: `docs/superpowers/specs/2026-08-03-news-and-canopy-atlas-modules-design.md`

## Global Constraints

- 300-line cap on every `.py` / `.ts` / `.tsx`. No exemptions under `modules/`.
  Enforced by `scripts/check_file_size.py`.
- Published modules depend on the framework with **ranges**
  (`simple_module_core>=0.0.25,<0.1`); the host pins **exactly**
  (`simple_module_hosting==0.0.25`). Never give a published module an `==` pin.
- Migrations live in `host/migrations/versions/`, never in a module. A module's
  first revision carries `branch_labels = ("<module>",)`.
- Nothing under `modules/*/*/pages/` unless it is a real Inertia page —
  `import.meta.glob` derives the page name from that path.
- One version across the repo (currently `0.1.0`); only
  `scripts/bump_version.py` edits versions, and it must never rewrite framework
  dependency specifiers. CI runs `--check-current`.
- Run Python entry points from the repo root.
- Framework work happens in `/Volumes/ext1/GitHub/simple_module_python` on a
  branch off `v0.0.25`. Do not push or release it.
- After every framework change, re-run
  `make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python`
  so the host picks it up.
- Full check before each commit: `make lint && make test-py && make e2e`.

---

## File Structure

**Framework** (`/Volumes/ext1/GitHub/simple_module_python`)

| File | Responsibility |
|---|---|
| `framework/core/simple_module_core/design_packs.py` | `DesignPack`, `DesignPackRegistry` |
| `framework/core/simple_module_core/__init__.py` | re-export both |
| `framework/core/simple_module_core/module.py` | `register_design_packs` hook |
| `framework/hosting/simple_module_hosting/app_builder.py` | call the hook, store `app.state.design_packs` |
| `modules/branding/branding/settings.py` | `design_pack` field + slug validator |
| `modules/branding/branding/contracts/schemas.py` | `design_pack` on `BrandingOut` / `BrandingUpdate` |
| `modules/branding/branding/shared_props.py` | `designPack` in the payload |
| `modules/branding/branding/endpoints/api.py` | reject an unregistered pack |
| `modules/branding/branding/endpoints/views.py` | pass `designPacks` page prop |
| `modules/branding/branding/pages/Manage.tsx` | pack dropdown |
| `packages/ui/src/types.ts` | `designPack` on `SharedProps["branding"]` |

**This repo**

| File | Responsibility |
|---|---|
| `modules/canopy_atlas/canopy_atlas/module.py` | meta, static mount, public route, pack registration |
| `modules/canopy_atlas/canopy_atlas/static/gca-pack.css` | the pack (moved) |
| `modules/canopy_atlas/canopy_atlas/static/gca/**` | photographs, logos, partner marks (moved) |
| `modules/canopy_atlas/canopy_atlas/seed/__main__.py` | CLI entry point |
| `modules/canopy_atlas/canopy_atlas/seed/uploads.py` | image upload + path rewriting |
| `modules/canopy_atlas/canopy_atlas/seed/pages.py` | page + layout + branding seeding |
| `modules/canopy_atlas/canopy_atlas/seed/content/*.json` | 12 pages + `_layout.json` (moved) |
| `modules/pagebuilder/pagebuilder/components/blockRegistry.ts` | registry + version counter |
| `modules/pagebuilder/pagebuilder/components/puckConfig.tsx` | `getPuckConfig()` |
| `modules/pagebuilder/pagebuilder/components/widgets/article-cards-render.tsx` | presentation, split out of the widget |
| `host/client_app/blocks.ts` | eager glob of every module's `puck-blocks.ts` |
| `modules/news/news/models.py` | `NewsArticle` sidecar |
| `modules/news/news/service.py` | listing + category queries |
| `modules/news/news/endpoints/api.py` | `/api/news` routes |
| `modules/news/news/pages/NewsList.tsx` | admin list (Inertia page) |
| `modules/news/news/components/NewsFeed.tsx` | the block's render |
| `modules/news/news/puck-blocks.ts` | registration side effect |

**Deleted:** `scripts/gca/`, `host/static/gca/`,
`modules/pagebuilder/pagebuilder/static/gca-pack.css`.

---

## Task 1: `DesignPackRegistry` in core

**Files:**
- Create: `framework/core/simple_module_core/design_packs.py`
- Modify: `framework/core/simple_module_core/__init__.py`,
  `framework/core/simple_module_core/module.py`,
  `framework/hosting/simple_module_hosting/app_builder.py:231-238`
- Test: `framework/core/tests/test_design_packs.py`

**Interfaces:**
- Produces: `DesignPack(value: str, label: str)` frozen dataclass;
  `DesignPackRegistry.register(pack) -> None`, `.all() -> list[DesignPack]`,
  `.values() -> set[str]`; `ModuleBase.register_design_packs(registry) -> None`;
  `app.state.design_packs: DesignPackRegistry`.

- [ ] **Step 1: Write the failing test**

```python
# framework/core/tests/test_design_packs.py
import pytest

from simple_module_core.design_packs import DesignPack, DesignPackRegistry


def test_registers_and_sorts_by_label():
    reg = DesignPackRegistry()
    reg.register(DesignPack(value="gca", label="Canopy Atlas"))
    reg.register(DesignPack(value="acme", label="Acme"))
    assert [p.value for p in reg.all()] == ["acme", "gca"]
    assert reg.values() == {"acme", "gca"}


def test_duplicate_value_is_an_error():
    # Two modules claiming one root class would silently resolve to whichever
    # stylesheet loaded last, so this has to be loud.
    reg = DesignPackRegistry()
    reg.register(DesignPack(value="gca", label="Canopy Atlas"))
    with pytest.raises(ValueError, match="gca"):
        reg.register(DesignPack(value="gca", label="Other"))


@pytest.mark.parametrize("bad", ["", "-gca", "GCA", "gca root", "gca_root"])
def test_rejects_values_that_are_not_class_safe(bad):
    reg = DesignPackRegistry()
    with pytest.raises(ValueError):
        reg.register(DesignPack(value=bad, label="X"))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && uv run pytest framework/core/tests/test_design_packs.py -v`
Expected: FAIL — `ModuleNotFoundError: simple_module_core.design_packs`

- [ ] **Step 3: Implement**

```python
# framework/core/simple_module_core/design_packs.py
"""Design packs — modules contribute site themes, branding picks one.

A pack is a CSS bundle scoped to a root class. The registry holds only the
name and label: the stylesheet itself reaches the browser through the host's
own CSS entry point, exactly like any other module stylesheet. Its job is to
stop an administrator selecting a pack no installed module provides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class DesignPack:
    """A selectable site theme."""

    value: str
    """Slug. The site root class is ``f"{value}-root"``."""
    label: str
    """Shown in the branding dropdown."""


class DesignPackRegistry:
    """Collects design packs from all modules."""

    def __init__(self) -> None:
        self._packs: dict[str, DesignPack] = {}

    def register(self, pack: DesignPack) -> None:
        if not _VALUE_RE.match(pack.value):
            raise ValueError(
                f"design pack value {pack.value!r} must match {_VALUE_RE.pattern} "
                "— it is interpolated into a CSS class name"
            )
        existing = self._packs.get(pack.value)
        if existing is not None:
            raise ValueError(
                f"design pack {pack.value!r} is already registered as "
                f"{existing.label!r}; two packs cannot share a root class"
            )
        self._packs[pack.value] = pack

    def all(self) -> list[DesignPack]:
        return sorted(self._packs.values(), key=lambda p: p.label.lower())

    def values(self) -> set[str]:
        return set(self._packs)
```

- [ ] **Step 4: Run it and watch it pass**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && uv run pytest framework/core/tests/test_design_packs.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the hook and the host wiring**

In `framework/core/simple_module_core/module.py`, beside
`register_public_routes`:

```python
    def register_design_packs(self, registry: DesignPackRegistry) -> None:
        """Contribute selectable site themes. Default: none."""
        return None
```

In `framework/core/simple_module_core/__init__.py`, beside the `menu` import:

```python
from simple_module_core.design_packs import DesignPack, DesignPackRegistry
```

and add both names to `__all__`.

In `app_builder.py`, construct `design_pack_registry = DesignPackRegistry()`
with the other registries, add `mod.register_design_packs(design_pack_registry)`
to the Phase 5 loop, and after the loop:

```python
    app.state.design_packs = design_pack_registry
```

Extend the existing "Registered %d menu items, …" log line with
`%d design packs` / `len(design_pack_registry.all())`.

- [ ] **Step 6: Run the framework suite**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && uv run pytest framework/core framework/hosting -q`
Expected: PASS

- [ ] **Step 7: Commit (framework repo)**

```bash
cd /Volumes/ext1/GitHub/simple_module_python
git switch -c feature/design-pack-registry
git add framework/core framework/hosting
git commit -m "feat(core): add DesignPackRegistry so modules can contribute site themes"
```

---

## Task 2: `design_pack` in branding

**Files:**
- Modify: `modules/branding/branding/settings.py`,
  `modules/branding/branding/contracts/schemas.py`,
  `modules/branding/branding/shared_props.py`,
  `modules/branding/branding/endpoints/api.py`,
  `modules/branding/branding/endpoints/views.py`,
  `modules/branding/branding/pages/Manage.tsx`,
  `packages/ui/src/types.ts`
- Test: `modules/branding/tests/test_branding.py`

**Interfaces:**
- Consumes: `DesignPack`, `DesignPackRegistry`, `app.state.design_packs`.
- Produces: `BrandingOut.design_pack: str`; `BrandingUpdate.design_pack: str | None`;
  shared prop `branding.designPack: string | null`; page prop
  `designPacks: {value, label}[]` on `Branding/Manage`.

- [ ] **Step 1: Write the failing tests**

```python
# append to modules/branding/tests/test_branding.py
import pytest
from simple_module_core.design_packs import DesignPack


@pytest.mark.asyncio
async def test_design_pack_round_trips(client, app):
    app.state.design_packs.register(DesignPack(value="gca", label="Canopy Atlas"))
    response = await client.put("/api/branding/", json={"design_pack": "gca"})
    assert response.status_code == 200
    assert response.json()["design_pack"] == "gca"


@pytest.mark.asyncio
async def test_unregistered_design_pack_is_rejected(client):
    response = await client.put("/api/branding/", json={"design_pack": "nope"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_design_pack_can_be_cleared(client, app):
    app.state.design_packs.register(DesignPack(value="gca", label="Canopy Atlas"))
    await client.put("/api/branding/", json={"design_pack": "gca"})
    response = await client.put("/api/branding/", json={"design_pack": ""})
    assert response.status_code == 200
    assert response.json()["design_pack"] == ""
```

Match the existing fixtures in that file — if it authenticates through a
different helper, use the same one rather than inventing `client`.

- [ ] **Step 2: Run and watch fail**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && uv run pytest modules/branding -k design_pack -v`
Expected: FAIL — the field does not exist, so `design_pack` is dropped and the
response has no such key.

- [ ] **Step 3: Backend implementation**

`settings.py` — add beside `primary_color`:

```python
    design_pack: str = ""  # "" = base tokens only; otherwise a registered slug

    @field_validator("design_pack")
    @classmethod
    def _valid_pack(cls, value: str) -> str:
        # Shape only. Whether the pack is *installed* is checked in the
        # endpoint, where the registry on app.state is reachable.
        if value and not DESIGN_PACK_RE.match(value):
            raise ValueError("design_pack must be a lowercase slug or empty")
        return value
```

with `DESIGN_PACK_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")` in
`branding/constants.py`.

`contracts/schemas.py` — `design_pack: str = ""` on `BrandingOut`, and
`design_pack: str | None = Field(default=None)` on `BrandingUpdate` with the
same shape validator.

`shared_props.py` — in `branding_payload`:

```python
        "designPack": settings.design_pack or None,
```

`endpoints/api.py` — `update_branding` gains the registry check. Note the
existing body drops `None` values, so `""` still reaches `apply` and clears
the pack:

```python
@router.put("/", response_model=BrandingOut, dependencies=[_MANAGE])
async def update_branding(
    data: BrandingUpdate, service: BrandingServiceDep, request: Request
) -> BrandingOut:
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    pack = changes.get("design_pack")
    if pack:
        registry = getattr(request.app.state, "design_packs", None)
        known = registry.values() if registry is not None else set()
        if pack not in known:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown design pack {pack!r}. Installed: {sorted(known) or 'none'}",
            )
    if not changes:
        return service.current()
    return await service.apply(changes)
```

`endpoints/views.py` — supply the dropdown options:

```python
async def manage(inertia: InertiaDep, request: Request) -> InertiaResponse:
    registry = getattr(request.app.state, "design_packs", None)
    packs = [{"value": p.value, "label": p.label} for p in registry.all()] if registry else []
    return await inertia.render(
        "Branding/Manage",
        {"designPacks": packs},
    )
```

Keep the existing comment about the inlined page-name literal.

- [ ] **Step 4: Run and watch pass**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && uv run pytest modules/branding -v`
Expected: PASS

- [ ] **Step 5: Frontend**

`packages/ui/src/types.ts` — add to the branding block:

```ts
  designPack: string | null;
```

`modules/branding/branding/pages/Manage.tsx` — read the new page prop and
render a select under the primary-colour field. Use the same `Label` +
`Select` primitives the page already imports; if it has no `Select` import,
use a native `<select>` styled with the same classes as the existing inputs
rather than adding a dependency.

```tsx
const { designPacks = [] } = usePage<{ props: { designPacks?: Pack[] } }>()
  .props as unknown as { designPacks?: Pack[] };
const [pack, setPack] = useState(branding?.designPack ?? '');
```

Include `design_pack: pack` in the existing save `body`. Add its label and
help text to `branding/locales/en.json` under the same `branding.manage.*`
prefix the other fields use — the repo's `check_hardcoded_strings.py`
equivalent runs in framework CI.

- [ ] **Step 6: Run the framework checks**

Run: `cd /Volumes/ext1/GitHub/simple_module_python && make lint && make test`
Expected: PASS

- [ ] **Step 7: Commit and link**

```bash
cd /Volumes/ext1/GitHub/simple_module_python
git add modules/branding packages/ui
git commit -m "feat(branding): add a design_pack setting backed by DesignPackRegistry"

cd /Volumes/ext1/emdash/worktrees/simple_module_python_modules/features/init-i8ghw
make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
```

---

## Task 3: `canopy_atlas` module shell

**Files:**
- Create: `modules/canopy_atlas/**` (scaffolded)
- Modify: `modules/canopy_atlas/canopy_atlas/module.py`,
  `host/pyproject.toml`
- Test: `modules/canopy_atlas/tests/test_module.py`

**Interfaces:**
- Produces: module `CanopyAtlas`, static mount `/canopy-atlas/static`,
  registered pack `("gca", "Canopy Atlas")`.

- [ ] **Step 1: Scaffold**

```bash
make new-module name=canopy_atlas
```

Then add to `host/pyproject.toml` dependencies:
`"simple_module_canopy_atlas",` and under `[tool.uv.sources]`:
`simple_module_canopy_atlas = { workspace = true }`. Run `make install`.

- [ ] **Step 2: Write the failing test**

```python
# modules/canopy_atlas/tests/test_module.py
"""The static mount is the module's whole public surface, and a mount is not
public by default — AuthMiddleware gates every request, so without a
PublicRouteRegistry entry every logo 302s to the login page."""

from simple_module_core.design_packs import DesignPackRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from canopy_atlas.module import CanopyAtlasModule


def test_registers_the_gca_pack():
    registry = DesignPackRegistry()
    CanopyAtlasModule().register_design_packs(registry)
    assert [(p.value, p.label) for p in registry.all()] == [("gca", "Canopy Atlas")]


def test_static_mount_is_public_and_does_not_leak_to_siblings():
    registry = PublicRouteRegistry()
    CanopyAtlasModule().register_public_routes(registry)
    prefixes = [r.path for r in registry.routes]
    assert "/canopy-atlas/static/" in prefixes
    # Public-route rules match with str.startswith; without the trailing slash
    # this prefix would also exempt /canopy-atlas/static-admin and friends.
    assert "/canopy-atlas/static" not in prefixes


def test_static_directory_ships_with_the_package():
    mounts = CanopyAtlasModule().static_mounts()
    directory = mounts["/canopy-atlas/static"]
    assert directory.is_dir()
```

Adapt attribute access (`r.path`) to whatever `PublicRoute` actually exposes —
read `simple_module_core/public_routes.py` first.

- [ ] **Step 3: Run and watch fail**

Run: `cd modules/canopy_atlas && uv run pytest -v`
Expected: FAIL — the hooks are not implemented.

- [ ] **Step 4: Implement `module.py`**

```python
"""Canopy Atlas — the Global Canopy Atlas site: design pack, assets, seed."""

from __future__ import annotations

import importlib.metadata
from importlib.resources import files
from pathlib import Path

from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.design_packs import DesignPack, DesignPackRegistry
from simple_module_core.public_routes import PublicRouteRegistry

_VERSION = importlib.metadata.version("simple_module_canopy_atlas")

_STATIC_MOUNT = "/canopy-atlas/static"
DESIGN_PACK = DesignPack(value="gca", label="Canopy Atlas")


class CanopyAtlasModule(ModuleBase):
    meta = ModuleMeta(
        name="CanopyAtlas",
        route_prefix="/api/canopy-atlas",
        view_prefix="/canopy-atlas",
        depends_on=["PageBuilder"],
        version=_VERSION,
        requires_framework=">=1.0,<2.0",
    )

    def static_mounts(self) -> dict[str, Path]:
        return {_STATIC_MOUNT: Path(str(files("canopy_atlas") / "static"))}

    def register_design_packs(self, registry: DesignPackRegistry) -> None:
        registry.register(DESIGN_PACK)

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        # Trailing slash: rules match with str.startswith, so the bare prefix
        # would also exempt any sibling path that merely starts with it.
        registry.add_prefix(f"{_STATIC_MOUNT}/")
```

Use whatever `PublicRouteRegistry` method `pagebuilder/module.py` uses —
copy its call shape exactly.

Create `modules/canopy_atlas/canopy_atlas/static/.gitkeep` so the directory
exists before Task 4 fills it, and make sure `pyproject.toml` includes
`static/**` in the wheel (follow pagebuilder's `[tool.hatch.build]` section —
note it uses `artifacts` for gitignored output, which does not apply here).

- [ ] **Step 5: Run and watch pass**

Run: `cd modules/canopy_atlas && uv run pytest -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Boot the host and confirm the module loads**

```bash
make kill; make dev > /tmp/dev.log 2>&1 &
sleep 8; curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8000/users/login
grep -i "canopyatlas\|design pack" /tmp/dev.log | head
```
Expected: `200`, and the startup log reports 1 design pack.

- [ ] **Step 7: Commit**

```bash
git add modules/canopy_atlas host/pyproject.toml uv.lock
git commit -m "feat(canopy-atlas): scaffold the module with its static mount and design pack"
```

---

## Task 4: move the pack and the assets

**Files:**
- Move: `modules/pagebuilder/pagebuilder/static/gca-pack.css` →
  `modules/canopy_atlas/canopy_atlas/static/gca-pack.css`;
  `host/static/gca/**` → `modules/canopy_atlas/canopy_atlas/static/gca/**`
- Modify: `host/client_app/styles.css`
- Test: `modules/canopy_atlas/tests/test_assets.py`

**Interfaces:**
- Consumes: the static mount from Task 3.
- Produces: assets served at `/canopy-atlas/static/gca/...`.

- [ ] **Step 1: Write the failing test**

```python
# modules/canopy_atlas/tests/test_assets.py
from importlib.resources import files

STATIC = files("canopy_atlas") / "static"

EXPECTED_PHOTOS = {
    "atlas-map.jpg", "biodiversity.jpg", "canopy-aerial.jpg", "canopy-up.jpg",
    "collaboration.jpg", "forest-aerial-river.jpg", "governance-diagram.jpg",
    "hero-lidar.jpg",
}
EXPECTED_PARTNERS = {
    "bristol.svg", "erc.svg", "esa.svg", "geo-trees.svg", "iiasa.svg",
    "leverhulme.svg", "ukri.svg",
}


def test_ships_the_photographs():
    names = {p.name for p in (STATIC / "gca" / "images").iterdir()}
    assert EXPECTED_PHOTOS <= names


def test_ships_the_brand_and_partner_marks():
    assert (STATIC / "gca" / "logo-main.svg").is_file()
    assert (STATIC / "gca" / "logo-reversed.svg").is_file()
    names = {p.name for p in (STATIC / "gca" / "partners").iterdir()}
    assert EXPECTED_PARTNERS <= names


def test_ships_the_design_pack_stylesheet():
    css = (STATIC / "gca-pack.css").read_text()
    assert ".gca-root" in css
```

- [ ] **Step 2: Run and watch fail**

Run: `cd modules/canopy_atlas && uv run pytest tests/test_assets.py -v`
Expected: FAIL — the directories do not exist.

- [ ] **Step 3: Move the files**

```bash
cd /Volumes/ext1/emdash/worktrees/simple_module_python_modules/features/init-i8ghw
DEST=modules/canopy_atlas/canopy_atlas/static
git mv modules/pagebuilder/pagebuilder/static/gca-pack.css "$DEST/gca-pack.css"
mkdir -p "$DEST/gca"
git mv host/static/gca/images "$DEST/gca/images"
git mv host/static/gca/partners "$DEST/gca/partners"
git mv host/static/gca/logo-main.svg host/static/gca/logo-reversed.svg "$DEST/gca/"
rmdir host/static/gca 2>/dev/null || true
```

- [ ] **Step 4: Repoint the host stylesheet**

In `host/client_app/styles.css` change the pack import to the new package and
extend the comment to say the pack now ships with `canopy_atlas`:

```css
@import "@simple-module-py/pagebuilder/pagebuilder/static/widgets-base.css";
@import "@simple-module-py/canopy-atlas/canopy_atlas/static/gca-pack.css";
```

Add `modules/canopy_atlas` to the npm workspace if `make new-module` did not,
and give it a `package.json` with `"name": "@simple-module-py/canopy-atlas"`
mirroring pagebuilder's.

- [ ] **Step 5: Run and watch pass**

Run: `cd modules/canopy_atlas && uv run pytest -v && cd - && make lint`
Expected: PASS

- [ ] **Step 6: Confirm the assets serve anonymously**

```bash
make kill; make dev > /tmp/dev.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "logo:%{http_code}\n" http://localhost:8000/canopy-atlas/static/gca/logo-main.svg
curl -s -o /dev/null -w "photo:%{http_code}\n" http://localhost:8000/canopy-atlas/static/gca/images/hero-lidar.jpg
```
Expected: both `200`. A `302` means the public-route prefix is wrong.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(canopy-atlas): move the GCA design pack and brand assets into the module"
```

---

## Task 5: move the seed into the module

**Files:**
- Create: `modules/canopy_atlas/canopy_atlas/seed/__init__.py`,
  `__main__.py`, `uploads.py`, `pages.py`, `content/` (moved JSON)
- Delete: `scripts/gca/`
- Test: `modules/canopy_atlas/tests/test_seed_rewrite.py`

**Interfaces:**
- Consumes: assets from Task 4.
- Produces: `python -m canopy_atlas.seed [--base-url URL] [--email] [--password] [--no-publish]`;
  `rewrite_asset_paths(node, uploads) -> Any`;
  `STATIC_PREFIX = "/canopy-atlas/static"`.

- [ ] **Step 1: Write the failing test**

```python
# modules/canopy_atlas/tests/test_seed_rewrite.py
from canopy_atlas.seed.uploads import rewrite_asset_paths

UPLOADS = {"/gca/images/hero-lidar.jpg": "/media/pagebuilder/abc.jpg"}


def test_photographs_become_media_library_urls():
    node = {"props": {"imageUrl": "/gca/images/hero-lidar.jpg"}}
    assert rewrite_asset_paths(node, UPLOADS)["props"]["imageUrl"] == "/media/pagebuilder/abc.jpg"


def test_svg_marks_move_to_the_module_static_mount():
    # SVG stays a file: the media library rejects it because it can carry
    # script and is served same-origin.
    node = ["/gca/logo-main.svg", "/gca/partners/iiasa.svg"]
    assert rewrite_asset_paths(node, UPLOADS) == [
        "/canopy-atlas/static/gca/logo-main.svg",
        "/canopy-atlas/static/gca/partners/iiasa.svg",
    ]


def test_in_site_links_are_left_alone():
    assert rewrite_asset_paths("/p/contact", UPLOADS) == "/p/contact"
    assert rewrite_asset_paths("/gca/contact", UPLOADS) == "/gca/contact"
```

- [ ] **Step 2: Run and watch fail**

Run: `cd modules/canopy_atlas && uv run pytest tests/test_seed_rewrite.py -v`
Expected: FAIL — `ModuleNotFoundError: canopy_atlas.seed`

- [ ] **Step 3: Move and split the seed**

`git mv scripts/gca/content modules/canopy_atlas/canopy_atlas/seed/content`,
then split `scripts/gca/seed_pages.py` (262 lines) across:

- `uploads.py` — `upload_images`, `rewrite_asset_paths`, `STATIC_PREFIX`,
  `GCA_STATIC_LOGOS`
- `pages.py` — `login`, `csrf_headers`, `seed_branding`, `seed_layout`,
  `seed_pages`
- `__main__.py` — argparse and the `httpx.Client` lifecycle

Change `rewrite_asset_paths` so both the partner marks *and* the two lockups
resolve to `f"{STATIC_PREFIX}{node}"` instead of `/static{node}`. Change
`IMAGE_DIR` to `files("canopy_atlas") / "static" / "gca" / "images"`.

`seed_branding` gains `"design_pack": "gca"` in its PUT body.

Delete `scripts/gca/`.

- [ ] **Step 4: Run and watch pass**

Run: `cd modules/canopy_atlas && uv run pytest -v`
Expected: PASS

- [ ] **Step 5: Seed a clean database end to end**

```bash
make kill; rm -f host/app.db; rm -rf var/pagebuilder/media
make migrate >/dev/null && make dev > /tmp/dev.log 2>&1 &
sleep 10
uv run python -m canopy_atlas.seed
```
Expected: `Seeded 12/12 pages.`, branding reports `design_pack` set, and
`Site layout: 3 header/footer block(s).`

Then check the public page has no broken images:

```bash
curl -s http://localhost:8000/p/home | grep -o '/canopy-atlas/static/gca/[^"]*' | sort -u | head
```
Expected: the logos and partner marks, all resolving.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(canopy-atlas): move the GCA seed into the module as python -m canopy_atlas.seed"
```

---

## Task 6: remove `designPack` from the page

**Files:**
- Modify: `modules/pagebuilder/pagebuilder/components/puckConfig.tsx`,
  `modules/pagebuilder/pagebuilder/pages/PublicPage.tsx`,
  `modules/canopy_atlas/canopy_atlas/seed/content/*.json`,
  `tests/e2e/widgets.spec.ts`, `tests/e2e/branding.spec.ts`,
  `tests/e2e/site-chrome.spec.ts`
- Test: `tests/e2e/design-pack.spec.ts` (new)

**Interfaces:**
- Consumes: `branding.designPack` shared prop (Task 2).
- Produces: `PageRootProps = { title: string; width: 'contained' | 'full' }`.

- [ ] **Step 1: Write the failing e2e**

```ts
// tests/e2e/design-pack.spec.ts
import { expect, test } from '@playwright/test';
import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The pack is a branding setting, not a page property: one site, one look.
 * Switching it in Settings -> Branding must re-theme every published page
 * without touching page content.
 */
test.describe('Design pack comes from branding', () => {
  test.describe.configure({ mode: 'serial' });

  test('switching the branding pack re-themes a published page', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('e2e-pack');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: {
        title: 'Pack',
        slug,
        draft_data: {
          root: { props: { title: 'Pack', width: 'full' } },
          content: [
            { type: 'Heading', props: { id: 'h', text: 'Pack', level: 'h1', align: 'left' } },
          ],
          zones: {},
        },
      },
    });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers: await csrfHeader(page),
      data: { note: 'pack' },
    });

    await page.goto('/branding');
    const cookies = await page.context().cookies();
    const token = cookies.find((c) => c.name === 'branding_csrf')?.value;
    const headers = token ? { 'X-CSRF-Token': decodeURIComponent(token) } : {};

    await page.request.put('/api/branding/', { headers, data: { design_pack: 'gca' } });
    await page.goto(`/p/${slug}?cb=on`);
    await expect(page.locator('.gca-root')).toHaveCount(1);

    await page.request.put('/api/branding/', { headers, data: { design_pack: '' } });
    await page.goto(`/p/${slug}?cb=off`);
    await expect(page.locator('.gca-root')).toHaveCount(0);

    await page.request.put('/api/branding/', { headers, data: { design_pack: 'gca' } });
  });
});
```

- [ ] **Step 2: Run and watch fail**

Run: `npx playwright test tests/e2e/design-pack.spec.ts --reporter=line`
Expected: FAIL — the page still carries its own `designPack`, so the count is
wrong in at least one branch.

- [ ] **Step 3: Strip the prop**

In `puckConfig.tsx`: delete the `designPack` field from `root.fields`, drop it
from `root.defaultProps` and from `emptyData.root.props`, remove it from
`PageRootProps`, and simplify `root.render` to apply only the width class.

In `PublicPage.tsx`: replace the `data.root.props.designPack` dig with the
shared prop, and update the comment to say the pack is site-wide:

```tsx
const { branding } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
const pack = branding?.designPack ?? null;
...
<div className={pack ? `${pack}-root` : undefined}>
```

Strip `"designPack"` from every `root.props` in
`modules/canopy_atlas/canopy_atlas/seed/content/*.json`:

```bash
cd modules/canopy_atlas/canopy_atlas/seed/content
python3 - <<'PY'
import json, pathlib
for p in pathlib.Path('.').glob('*.json'):
    d = json.loads(p.read_text())
    props = d.get('root', {}).get('props')
    if isinstance(props, dict):
        props.pop('designPack', None)
    p.write_text(json.dumps(d, indent=2) + "\n")
PY
```

`seed/pages.py` stops writing `designPack` into the root props it sets.

- [ ] **Step 4: Fix the assertions the change invalidates**

`tests/e2e/widgets.spec.ts` — the two-root assertion becomes one, since only
PublicPage's hoisted wrapper remains:

```ts
    // One root now: the pack is a site-wide branding setting, so PublicPage
    // wraps the whole document and the page root no longer renders its own.
    await expect(page.locator('.gca-root')).toHaveCount(1);
```

Delete the `main .gca-root` assertion below it.

`branding.spec.ts` and `site-chrome.spec.ts` build pages with
`designPack: 'gca'` in their root props — remove it from both, and make sure
their `beforeAll` sets branding's pack to `gca` so `.gca-root` still exists
for `packVar` to read.

- [ ] **Step 5: Run everything**

Run: `make lint && make test-py && make e2e`
Expected: PASS

- [ ] **Step 6: Re-seed and eyeball the site**

```bash
uv run python -m canopy_atlas.seed
```
Then load `http://localhost:8000/p/home` and confirm it still renders in the
GCA pack — ink headings, Plus Jakarta type, sticky header.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(pagebuilder): take the design pack from branding, not page props"
```

---

## Task 7: block registry in `pagebuilder`

**Files:**
- Create: `modules/pagebuilder/pagebuilder/components/blockRegistry.ts`
- Modify: `modules/pagebuilder/pagebuilder/components/puckConfig.tsx`,
  `modules/pagebuilder/pagebuilder/components/layoutPuckConfig.tsx`,
  `modules/pagebuilder/pagebuilder/pages/PageEditor.tsx`,
  `modules/pagebuilder/pagebuilder/pages/PublicPage.tsx`
- Test: `modules/pagebuilder/pagebuilder/components/blockRegistry.test.ts`

**Interfaces:**
- Produces: `registerPuckBlocks(registration: BlockRegistration): void`,
  `registeredBlocks(): BlockRegistration[]`, `registryVersion(): number`,
  `resetBlockRegistry(): void` (tests only), `getPuckConfig(): Config`,
  `getLayoutPuckConfig(): Config`.

```ts
export interface BlockRegistration {
  blocks: Record<string, ComponentConfig<never>>;
  category?: { key: string; title: string };
  layout?: boolean;
}
```

- [ ] **Step 1: Write the failing test**

```ts
// modules/pagebuilder/pagebuilder/components/blockRegistry.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

import {
  registerPuckBlocks,
  registryVersion,
  resetBlockRegistry,
} from './blockRegistry';
import { getPuckConfig } from './puckConfig';

const stub = { render: () => null } as never;

describe('block registry', () => {
  beforeEach(() => resetBlockRegistry());

  it('adds a registered block to the config', () => {
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(Object.keys(getPuckConfig().components)).toContain('Widget');
  });

  it('files a registered block under its category', () => {
    registerPuckBlocks({
      blocks: { Widget: stub },
      category: { key: 'feeds', title: 'Feeds' },
    });
    expect(getPuckConfig().categories?.feeds?.components).toEqual(['Widget']);
  });

  it('picks up a registration made after the first read', () => {
    // The config is memoised; keying the memo on the registry version is what
    // stops a late registration being silently dropped.
    expect(Object.keys(getPuckConfig().components)).not.toContain('Late');
    registerPuckBlocks({ blocks: { Late: stub } });
    expect(Object.keys(getPuckConfig().components)).toContain('Late');
  });

  it('refuses to shadow a built-in block', () => {
    expect(() => registerPuckBlocks({ blocks: { Heading: stub } })).toThrow(/Heading/);
  });

  it('bumps the version on each registration', () => {
    const before = registryVersion();
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(registryVersion()).toBeGreaterThan(before);
  });
});
```

Check `modules/pagebuilder/package.json` has a `test` script and vitest; if
not, add vitest as a devDependency and `"test": "vitest run"`, and wire
`make test-js` to run it for every module the same way `test-py` loops.

- [ ] **Step 2: Run and watch fail**

Run: `npx vitest run modules/pagebuilder/pagebuilder/components/blockRegistry.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the registry**

```ts
// modules/pagebuilder/pagebuilder/components/blockRegistry.ts
/**
 * Lets another module contribute Puck blocks without pagebuilder importing it.
 *
 * The framework's registries (menu, permissions, public routes) are all
 * backend, so this is the frontend equivalent. Registration is a side effect
 * of importing a module's `puck-blocks.ts`; the host imports them all eagerly
 * at app start, before anything renders.
 */

import type { ComponentConfig } from '@measured/puck';

export interface BlockRegistration {
  blocks: Record<string, ComponentConfig<never>>;
  /** Palette group. Omitted blocks land in Puck's "Other". */
  category?: { key: string; title: string };
  /** Also offer these in the site-layout palette. Default false. */
  layout?: boolean;
}

let registrations: BlockRegistration[] = [];
let version = 0;

export function registerPuckBlocks(registration: BlockRegistration): void {
  for (const name of Object.keys(registration.blocks)) {
    if (takenNames.has(name)) {
      throw new Error(
        `Puck block "${name}" is already registered. Block names are the keys ` +
          'of stored page content, so two blocks cannot share one.',
      );
    }
    takenNames.add(name);
  }
  registrations = [...registrations, registration];
  version += 1;
}

export function registeredBlocks(): BlockRegistration[] {
  return registrations;
}

export function registryVersion(): number {
  return version;
}

/** Test-only: drop every registration. */
export function resetBlockRegistry(): void {
  registrations = [];
  takenNames = new Set(BUILT_IN_NAMES);
  version += 1;
}
```

`BUILT_IN_NAMES` is a `readonly string[]` exported from `puckConfig.tsx`
listing the 20 built-in block keys plus `SiteHeader`/`SiteFooter`; import it
here and seed `takenNames` from it. Declare
`let takenNames = new Set<string>(BUILT_IN_NAMES);` above `registerPuckBlocks`.

- [ ] **Step 4: Convert the configs to functions**

In `puckConfig.tsx`, rename the exported const to `baseComponents` /
`baseCategories` and add:

```ts
let cached: Config<PuckComponents, PageRootProps> | null = null;
let cachedVersion = -1;

export function getPuckConfig(): Config<PuckComponents, PageRootProps> {
  if (cached && cachedVersion === registryVersion()) return cached;
  const components = { ...baseComponents };
  const categories = { ...baseCategories };
  for (const reg of registeredBlocks()) {
    Object.assign(components, reg.blocks);
    if (reg.category) {
      categories[reg.category.key] = {
        title: reg.category.title,
        components: [
          ...(categories[reg.category.key]?.components ?? []),
          ...Object.keys(reg.blocks),
        ],
      };
    }
  }
  cached = { root, categories, components } as Config<PuckComponents, PageRootProps>;
  cachedVersion = registryVersion();
  return cached;
}
```

Do the same in `layoutPuckConfig.tsx` as `getLayoutPuckConfig()`, including
only registrations with `layout: true`, and keep its own memo pair.

Update the three call sites to call the functions inside the component body:
`PageEditor.tsx` (`config={getPuckConfig()}`), `PublicPage.tsx` (both
`Render`s), and `layoutPuckConfig.tsx` itself.

- [ ] **Step 5: Run and watch pass**

Run: `npx vitest run modules/pagebuilder && make lint && make e2e`
Expected: PASS — the existing e2e proves the config still assembles.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(pagebuilder): add a Puck block registry so modules can contribute blocks"
```

---

## Task 8: host-side eager block imports

**Files:**
- Create: `host/client_app/blocks.ts`
- Modify: `host/client_app/app.tsx:1`
- Test: covered by Task 12's e2e; no unit test (it is a glob).

**Interfaces:**
- Consumes: `registerPuckBlocks` from Task 7.
- Produces: every installed module's `puck-blocks.ts` runs before the first render.

- [ ] **Step 1: Create the glob file**

```ts
// host/client_app/blocks.ts
/**
 * Eagerly run every module's Puck block registration.
 *
 * Module *pages* are imported lazily by Inertia's resolver, which is far too
 * late — a pagebuilder page reads the Puck config while rendering. Importing
 * the registrations here, from the app entry, guarantees the registry is
 * populated first.
 *
 * Two globs because workspace modules and wheel-installed modules live in
 * different trees, the same split modules.generated.ts uses for pages. This
 * file is hand-written for the same reason styles.css's module imports are:
 * gen-pages emits page globs and @source entries, not block imports.
 */
import.meta.glob('../../modules/*/*/puck-blocks.ts', { eager: true });
import.meta.glob('../../.venv/lib/python3.12/site-packages/*/puck-blocks.ts', {
  eager: true,
});
```

- [ ] **Step 2: Import it first from the app entry**

At the very top of `host/client_app/app.tsx`, above the Inertia imports:

```ts
import './blocks';
```

- [ ] **Step 3: Verify the app still boots**

```bash
make kill; make dev > /tmp/dev.log 2>&1 &
sleep 10; curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/p/home
```
Expected: `200`, no console error about an unresolved glob. Vite tolerates a
glob matching nothing, so this passes before any module ships the file.

- [ ] **Step 4: Commit**

```bash
git add host/client_app/blocks.ts host/client_app/app.tsx
git commit -m "feat(host): run every module's Puck block registration at app start"
```

---

## Task 9: `news` module and its table

**Files:**
- Create: `modules/news/**` (scaffolded), `modules/news/news/models.py`
- Create: `host/migrations/versions/<rev>_add_news.py` (autogenerated)
- Modify: `host/pyproject.toml`, `modules/news/pyproject.toml`
- Test: `modules/news/tests/test_models.py`

**Interfaces:**
- Produces: `NewsArticle` with `id`, `page_id`, `category`, `published_at`.

- [ ] **Step 1: Scaffold and declare the dependency**

```bash
make new-module name=news
```

In `modules/news/pyproject.toml`, add `"simple_module_pagebuilder>=0.1,<0.2"`
to `dependencies` — a **range**, never `==`. In `host/pyproject.toml` add
`"simple_module_news",` plus `[tool.uv.sources] simple_module_news = { workspace = true }`.
Run `make install`.

- [ ] **Step 2: Write the failing test**

```python
# modules/news/tests/test_models.py
from news.models import NewsArticle


def test_table_name_and_columns():
    assert NewsArticle.__tablename__ == "news_articles"
    columns = NewsArticle.__table__.columns
    assert {"id", "page_id", "category", "published_at"} <= set(columns.keys())


def test_page_id_is_unique_and_cascades():
    # One article row per page, and deleting the page takes the row with it —
    # otherwise a deleted page leaves an article pointing at nothing.
    page_id = NewsArticle.__table__.columns["page_id"]
    assert page_id.unique is True
    fk = next(iter(page_id.foreign_keys))
    assert fk.column.table.name == "pagebuilder_pages"
    assert fk.ondelete == "CASCADE"
```

- [ ] **Step 3: Run and watch fail**

Run: `cd modules/news && uv run pytest -v`
Expected: FAIL — `news.models` has no `NewsArticle`.

- [ ] **Step 4: Implement the model**

```python
"""SQLModel table for the news module.

An article *is* a pagebuilder page — title, slug, body, workflow, revisions
and SEO all live there. This table adds only what a page has no concept of:
which category the article belongs to and the date it should be listed under.
Keeping it a sidecar is what lets pagebuilder stay a generic CMS.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.base import create_module_base
from simple_module_db.mixins import AuditMixin
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field

Base = create_module_base("news")


class NewsArticle(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Article metadata attached to a pagebuilder page."""

    __tablename__ = "news_articles"

    id: int | None = Field(default=None, primary_key=True)
    page_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("pagebuilder_pages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    category: str = Field(default="", max_length=80, index=True)
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """The article's display date. Deliberately not ``Page.publish_at``, which
    is the single-shot scheduling field and is cleared on every flip."""
```

- [ ] **Step 5: Run and watch pass**

Run: `cd modules/news && uv run pytest -v`
Expected: PASS

- [ ] **Step 6: Generate and fix up the migration**

```bash
make migration msg="add news"
```

Open the generated file in `host/migrations/versions/` and add, beside
`down_revision`:

```python
branch_labels = ("news",)
depends_on = ("pagebuilder",)
```

`depends_on` matters: the foreign key crosses branch labels, and without it
`alembic upgrade heads` can order `news_articles` before `pagebuilder_pages`
exists. It only fails on a clean database, so it will not show up on a
machine that already has the table.

- [ ] **Step 7: Prove it on a clean database**

```bash
make kill; rm -f host/app.db
make migrate
```
Expected: no error. Then `make dev`, and re-seed with
`uv run python -m canopy_atlas.seed`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(news): add the article sidecar table keyed to pagebuilder pages"
```

---

## Task 10: news service and API

**Files:**
- Create: `modules/news/news/service.py`, `modules/news/news/contracts/schemas.py`,
  `modules/news/news/endpoints/api.py`, `modules/news/news/permissions.py`
- Modify: `modules/news/news/module.py`
- Test: `modules/news/tests/test_articles_api.py`

**Interfaces:**
- Consumes: `NewsArticle` (Task 9), `pagebuilder.models.Page`, `PageStatus`.
- Produces: `GET /api/news/articles`, `GET /api/news/categories`,
  `POST/PUT/DELETE /api/news/articles`; `ArticleRead` with
  `{id, page_id, slug, title, excerpt, cover_image_url, category, published_at, url}`.

- [ ] **Step 1: Write the failing tests**

```python
# modules/news/tests/test_articles_api.py
import pytest

# Fixtures follow modules/pagebuilder/tests/conftest.py — copy its app/client
# construction and add the news module alongside pagebuilder.


@pytest.mark.asyncio
async def test_anonymous_sees_published_articles_only(anon_client, make_article):
    await make_article(slug="live", published=True)
    await make_article(slug="wip", published=False)
    body = (await anon_client.get("/api/news/articles")).json()
    assert [i["slug"] for i in body["items"]] == ["live"]
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_orders_newest_first_with_undated_last(anon_client, make_article):
    await make_article(slug="old", published=True, published_at="2025-01-01T00:00:00Z")
    await make_article(slug="new", published=True, published_at="2026-01-01T00:00:00Z")
    await make_article(slug="undated", published=True, published_at=None)
    items = (await anon_client.get("/api/news/articles")).json()["items"]
    assert [i["slug"] for i in items] == ["new", "old", "undated"]


@pytest.mark.asyncio
async def test_filters_by_category(anon_client, make_article):
    await make_article(slug="a", published=True, category="Updates")
    await make_article(slug="b", published=True, category="Events")
    items = (await anon_client.get("/api/news/articles?category=Events")).json()["items"]
    assert [i["slug"] for i in items] == ["b"]


@pytest.mark.asyncio
async def test_categories_report_counts(anon_client, make_article):
    await make_article(slug="a", published=True, category="Updates")
    await make_article(slug="b", published=True, category="Updates")
    await make_article(slug="c", published=False, category="Events")
    body = (await anon_client.get("/api/news/categories")).json()
    assert body["items"] == [{"category": "Updates", "count": 2}]


@pytest.mark.asyncio
async def test_attaching_twice_is_a_conflict(client, make_page):
    page_id = await make_page(slug="once")
    assert (await client.post("/api/news/articles", json={"page_id": page_id})).status_code == 201
    assert (await client.post("/api/news/articles", json={"page_id": page_id})).status_code == 409


@pytest.mark.asyncio
async def test_deleting_the_page_removes_the_article_row(client, session, make_article):
    article_id = await make_article(slug="doomed", published=True)
    page_id = (await client.get(f"/api/news/articles")).json()["items"][0]["page_id"]
    await client.delete(f"/api/pagebuilder/pages/{page_id}")
    assert (await client.get("/api/news/articles")).json()["total"] == 0


@pytest.mark.asyncio
async def test_write_requires_permission(anon_client, make_page):
    page_id = await make_page(slug="guarded")
    response = await anon_client.post("/api/news/articles", json={"page_id": page_id})
    assert response.status_code in (401, 403)
```

- [ ] **Step 2: Run and watch fail**

Run: `cd modules/news && uv run pytest -v`
Expected: FAIL — the routes do not exist (404).

- [ ] **Step 3: Implement**

`permissions.py` — `PERM_VIEW = "news.view"`, `PERM_EDIT = "news.edit"`,
registered from `module.py`'s `register_permissions`, following
`pagebuilder/permissions.py`.

`service.py` — joins `NewsArticle` to `Page`:

```python
def _visible(stmt, *, include_drafts: bool):
    return stmt if include_drafts else stmt.where(Page.status == PageStatus.PUBLISHED)


async def list_articles(db, *, limit, offset, category, include_drafts):
    stmt = select(NewsArticle, Page).join(Page, Page.id == NewsArticle.page_id)
    stmt = _visible(stmt, include_drafts=include_drafts)
    if category:
        stmt = stmt.where(NewsArticle.category == category)
    # NULLS LAST so an undated article sorts after every dated one on both
    # SQLite and Postgres — SQLite puts NULL first by default.
    stmt = stmt.order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
    ...
```

`endpoints/api.py` — the five routes. Read routes carry no permission
dependency; write routes use `RequiresPermission(PERM_EDIT)`. `POST` returns
`201`, and catches the unique-constraint violation to return `409`.

`module.py` — `depends_on=["PageBuilder"]`, `register_permissions`, and
`register_public_routes` exempting `/api/news/articles` and
`/api/news/categories` so the feed block works for anonymous visitors.
Use `_dir_prefix`-style trailing-slash normalisation if registering prefixes.

- [ ] **Step 4: Run and watch pass**

Run: `cd modules/news && uv run pytest -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(news): list, filter and attach articles over pagebuilder pages"
```

---

## Task 11: news admin page

**Files:**
- Create: `modules/news/news/pages/NewsList.tsx`,
  `modules/news/news/components/ArticleRow.tsx`,
  `modules/news/news/utils/api.ts`, `modules/news/news/endpoints/views.py`
- Modify: `modules/news/news/module.py`
- Test: `tests/e2e/news-admin.spec.ts`

**Interfaces:**
- Consumes: the API from Task 10.
- Produces: admin view at `/news/`, menu item "News" in group "Content".

- [ ] **Step 1: Write the failing e2e**

```ts
// tests/e2e/news-admin.spec.ts
import { expect, test } from '@playwright/test';
import { login } from './helpers';

test.describe('News admin', () => {
  test('lists articles and reaches the editor', async ({ page }) => {
    await login(page);
    await page.goto('/news/');
    await expect(page.getByRole('heading', { name: 'News' })).toBeVisible();
    await expect(page.getByRole('button', { name: /new article/i })).toBeVisible();
  });

  test('is reachable from the sidebar', async ({ page }) => {
    await login(page);
    await page.goto('/dashboard/');
    await page.getByRole('link', { name: 'News' }).click();
    await expect(page).toHaveURL(/\/news\/?$/);
  });
});
```

- [ ] **Step 2: Run and watch fail**

Run: `npx playwright test tests/e2e/news-admin.spec.ts --reporter=line`
Expected: FAIL — `/news/` 404s.

- [ ] **Step 3: Implement**

`endpoints/views.py` mirrors branding's: one `@router.get("/")` rendering
`"News/NewsList"` behind `RequiresPermission(PERM_VIEW)`, with the page name
inlined as a literal so the SM003/SM004 diagnostics can pair it with the file.

`pages/NewsList.tsx` — the list. Keep it under 300 lines by putting the row
(inline category input, date input, save button, "Edit body" link) in
`components/ArticleRow.tsx` and the fetch helpers in `utils/api.ts`.
**Nothing else goes under `pages/`** — a stray `.tsx` there registers a page.

"New article" POSTs a page to `/api/pagebuilder/pages`, POSTs the article row
to `/api/news/articles`, then `router.visit(`/pagebuilder/${id}`)`.

`module.py` — `register_menu_items` adding
`MenuItem(label=..., url="/news/", icon="newspaper", group="Content")`,
following pagebuilder's. Roles stay empty: role filtering is a plain
intersection with **no admin bypass**, so a non-empty list hides the item from
everyone outside it.

Add `modules/news/news/locales/en.json` and route every visible string through
it — `scripts/check_hardcoded_strings.py` runs in `make lint`.

- [ ] **Step 4: Run and watch pass**

Run: `make lint && npx playwright test tests/e2e/news-admin.spec.ts --reporter=line`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(news): add the article admin list"
```

---

## Task 12: `NewsFeed` block

**Files:**
- Create: `modules/pagebuilder/pagebuilder/components/widgets/article-cards-render.tsx`,
  `modules/news/news/components/NewsFeed.tsx`,
  `modules/news/news/puck-blocks.ts`
- Modify: `modules/pagebuilder/pagebuilder/components/widgets/article-cards-widget.tsx`,
  `modules/pagebuilder/package.json` (export the render module)
- Test: `tests/e2e/news-feed.spec.ts`

**Interfaces:**
- Consumes: `registerPuckBlocks` (Task 7), `GET /api/news/articles` (Task 10).
- Produces: `ArticleCardsGrid({ items, columns })` exported from pagebuilder;
  block `NewsFeed` in category `feeds` / "Feeds".

- [ ] **Step 1: Write the failing e2e**

```ts
// tests/e2e/news-feed.spec.ts
import { expect, test } from '@playwright/test';
import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The feed is the only reason the block registry exists: pagebuilder must not
 * import news, so the block arrives through registration at app start.
 */
test.describe('News feed block', () => {
  test.describe.configure({ mode: 'serial' });

  test('is offered in the page palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: 'News feed' }).first(),
    ).toBeAttached();
  });

  test('renders live articles on a published page', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);

    const articleSlug = uniqueSlug('e2e-article');
    const article = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: 'A real article',
        slug: articleSlug,
        meta_description: 'The excerpt.',
        draft_data: {
          root: { props: { title: 'A real article', width: 'full' } },
          content: [
            { type: 'Heading', props: { id: 'h', text: 'Body', level: 'h1', align: 'left' } },
          ],
          zones: {},
        },
      },
    });
    const { id: articleId } = await article.json();
    await page.request.post(`/api/pagebuilder/pages/${articleId}/publish`, {
      headers,
      data: { note: 'article' },
    });
    await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: articleId, category: 'Updates', published_at: '2026-01-01T00:00:00Z' },
    });

    const indexSlug = uniqueSlug('e2e-feed');
    const index = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: 'Newsroom',
        slug: indexSlug,
        draft_data: {
          root: { props: { title: 'Newsroom', width: 'full' } },
          content: [
            {
              type: 'NewsFeed',
              props: { id: 'feed', heading: 'Latest', category: '', limit: 4, columns: '4',
                       viewAllLabel: '', viewAllHref: '' },
            },
          ],
          zones: {},
        },
      },
    });
    const { id: indexId } = await index.json();
    await page.request.post(`/api/pagebuilder/pages/${indexId}/publish`, {
      headers,
      data: { note: 'feed' },
    });

    await page.goto(`/p/${indexSlug}`);
    const card = page.getByRole('link', { name: /A real article/ });
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('href', `/p/${articleSlug}`);
  });
});
```

- [ ] **Step 2: Run and watch fail**

Run: `npx playwright test tests/e2e/news-feed.spec.ts --reporter=line`
Expected: FAIL — `NewsFeed` is not a registered block, so the page renders
nothing for it.

- [ ] **Step 3: Split the ArticleCards presentation out**

Move the grid markup from `article-cards-widget.tsx` into
`article-cards-render.tsx`, exporting:

```tsx
export interface ArticleCardItem {
  imageUrl: string;
  imageAlt: string;
  eyebrow: string;
  date: string;
  title: string;
  body: string;
  href: string;
}

export function ArticleCardsGrid({
  items,
  columns,
}: { items: ArticleCardItem[]; columns: '2' | '3' | '4' }): React.ReactElement
```

`article-cards-widget.tsx` keeps only the `ComponentConfig` and renders
through it — the same config/render split `faq-widget.tsx` already uses. Add
the file to pagebuilder's `package.json` `exports` if it pins specific
subpaths.

- [ ] **Step 4: Implement the block**

`modules/news/news/components/NewsFeed.tsx` — fetches
`/api/news/articles?limit=&category=` in a `useEffect`, maps rows to
`ArticleCardItem` (`href` = the row's `url`, `date` formatted from
`published_at`, `body` = excerpt), and renders `ArticleCardsGrid`. Empty and
error both render nothing on the public page and a one-line hint in the
editor — detect the editor with Puck's `isEditing` if the version exposes it,
otherwise accept the hint everywhere and say so in a comment.

`modules/news/news/puck-blocks.ts`:

```ts
import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { NewsFeedBlock } from './components/NewsFeed';

registerPuckBlocks({
  blocks: { NewsFeed: NewsFeedBlock },
  category: { key: 'feeds', title: 'Feeds' },
});
```

- [ ] **Step 5: Run and watch pass**

Run: `make lint && make test-py && make e2e`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(news): add the NewsFeed block, registered into pagebuilder"
```

---

## Task 13: seed real GCA articles

**Files:**
- Modify: `modules/canopy_atlas/canopy_atlas/seed/pages.py`,
  `modules/canopy_atlas/canopy_atlas/seed/content/home.json`,
  `modules/canopy_atlas/canopy_atlas/seed/content/news-index.json`
- Create: `modules/canopy_atlas/canopy_atlas/seed/content/_articles.json`
- Test: `modules/canopy_atlas/tests/test_seed_articles.py`

**Interfaces:**
- Consumes: `/api/news/articles` (Task 10), `NewsFeed` (Task 12).
- Produces: `seed_articles(client, base_url, headers, uploads) -> int`,
  returning 0 when the news module is absent.

- [ ] **Step 1: Write the failing test**

```python
# modules/canopy_atlas/tests/test_seed_articles.py
import httpx

from canopy_atlas.seed.pages import seed_articles


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")


def test_skips_seeding_when_news_is_not_installed():
    # canopy_atlas must not depend on news: a host that installs only the
    # atlas keeps the hand-authored cards.
    def handler(request):
        return httpx.Response(404)

    assert seed_articles(_client(handler), "http://t", {}, {}) == 0


def test_seeds_articles_when_news_answers():
    seen = []

    def handler(request):
        if request.url.path == "/api/news/articles" and request.method == "GET":
            return httpx.Response(200, json={"items": [], "total": 0})
        seen.append(request.url.path)
        return httpx.Response(201, json={"id": len(seen)})

    assert seed_articles(_client(handler), "http://t", {}, {}) > 0
    assert "/api/news/articles" in seen
```

- [ ] **Step 2: Run and watch fail**

Run: `cd modules/canopy_atlas && uv run pytest tests/test_seed_articles.py -v`
Expected: FAIL — `seed_articles` does not exist.

- [ ] **Step 3: Implement**

`_articles.json` holds the four articles the GCA home page already shows as
hardcoded cards — title, slug, excerpt, category, date, image path — lifted
verbatim from `home.json` so the seeded site says the same thing it does now.

```python
def seed_articles(client, base_url, headers, uploads) -> int:
    """Create the article pages and attach their news rows.

    Probes the news API first: canopy_atlas does not depend on news, so a host
    that installs only the atlas keeps the hand-authored cards.
    """
    probe = client.get(f"{base_url}/api/news/articles", headers={"Accept": "application/json"})
    if probe.status_code == 404:
        return 0
    ...
```

Then swap the `ArticleCards` block in `home.json` and `news-index.json` for a
`NewsFeed` block with the same heading and column count — but only when
articles were seeded. Do that by leaving the JSON with `ArticleCards` and
having `seed_articles` replace the block in the payload it sends, so a
news-less host still gets the original content.

- [ ] **Step 4: Run and watch pass**

Run: `cd modules/canopy_atlas && uv run pytest -v`
Expected: PASS

- [ ] **Step 5: Seed and look at the site**

```bash
make kill; rm -f host/app.db; rm -rf var/pagebuilder/media
make migrate >/dev/null && make dev > /tmp/dev.log 2>&1 &
sleep 10
uv run python -m canopy_atlas.seed
```
Then open `http://localhost:8000/p/home` and confirm the news strip shows the
seeded articles and each card links to `/p/{slug}`.

- [ ] **Step 6: Full suite**

Run: `make lint && make test-py && make e2e`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(canopy-atlas): seed real news articles when the news module is installed"
```

---

## Self-review

**Spec coverage.** Step 0 → Tasks 1–2. Step 1 → Tasks 3–6. Step 2 → Tasks 7–8.
Step 3 → Tasks 9–13. Step 4 (atlas map) is out of scope by design and has no
task, as the spec states.

**Known gaps carried from the spec, not bugs in this plan:**
- The framework changes cannot merge until a release is cut; Tasks 1–2 leave
  the framework on a local branch and the host on `make link-framework`.
- Risk 4 (Vite globbing `puck-blocks.ts` out of site-packages) is only
  exercised once a wheel-installed module ships one. Both modules here are
  workspace modules, so the second glob in Task 8 is unproven until then.
  Task 8 Step 3 confirms only that an empty glob is harmless.
