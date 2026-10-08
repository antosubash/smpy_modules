# Adding a module

Every step below is required. Missing the release-matrix entry is the easiest
one to forget and the one that silently skips your module at publish time.

## 1. Scaffold it

```bash
make new-module name=orders
```

This runs `smpy create-module orders --dest modules/orders`. It deliberately
omits `--standalone`: GitHub only runs workflows from the repository-root
`.github/workflows/`, so a nested per-module workflow would never fire, and a
nested `publish.yml` is a publish footgun.

## 2. Wire it into the host

In `host/pyproject.toml`, add the dependency and a workspace source:

```toml
dependencies = [
    ...
    "simple_module_orders",
]

[tool.uv.sources.simple_module_orders]
workspace = true
```

## 3. Complete its metadata

`scripts/check_metadata.py` requires all of these in
`modules/orders/pyproject.toml`:

```toml
[project]
name = "simple_module_orders"
version = "0.1.0"                 # must match the repo's current version
description = "..."               # not the scaffold placeholder
readme = "README.md"
license = "MIT"
keywords = ["simple-module", ...] # must include "simple-module"

[project.urls]
Repository = "https://github.com/antosubash/simple_module_python_modules"
```

Set `version` to whatever `scripts/bump_version.py --check-current` reports —
CI fails if it drifts from the root.

Pin the framework with **ranges**, never `==`:

```toml
dependencies = [
    "simple_module_core>=0.0.35,<0.1",
    "simple_module_db>=0.0.35,<0.1",
    "simple_module_hosting>=0.0.35,<0.1",
]
```

If the module ships a frontend, use hatchling's `artifacts` for the built
bundle rather than a force-include — the bundle is gitignored, and a
force-include fails when the path is absent from a clean checkout:

```toml
[tool.hatch.build.targets.wheel]
packages = ["orders"]
artifacts = ["orders/static/dist/**"]

[tool.hatch.build.targets.wheel.force-include]
"package.json" = "orders/package.json"

[tool.hatch.build.targets.sdist]
artifacts = ["orders/static/dist/**"]
```

## 4. Wire it into the UI and the auth layer

Two hooks are easy to forget because nothing fails loudly without them:

**`register_menu_items`** — without it the module boots and its routes work,
but nothing links to them. Note that menu role filtering is a plain
intersection with no admin bypass: listing roles hides the entry from an
`admin` user unless `"admin"` is among them. Leave `roles` empty when the
views are auth-gated rather than permission-gated.

**`register_public_routes`** — `AuthMiddleware` gates *every* request. Any
route meant for anonymous visitors (a public viewer, sitemap, robots, a
webhook) must be exempted here or it 302s to the login page. Two traps:

- Rules match with `startswith`, so terminate directory prefixes with `/`.
  A bare `/p` also matches `/pagebuilder/` — that hands your whole admin UI
  to anonymous visitors.
- Pin the methods (`{"GET", "HEAD"}`) so the exemption can't widen later.

Playwright specs run authenticated and will not catch a missing exemption.
Assert on the registry directly — see
`modules/pagebuilder/tests/test_public_routes.py`.

## 5. Write its README

`scripts/check_readmes.py` requires an H1, at least 500 bytes, and the words
"Install" and "Usage". Cover what the module does, installation, its settings
and permissions, and its routes.

## 6. Register its tests

Add `modules/orders/tests` to `testpaths` in the root `pyproject.toml`.
`make test-py` discovers `modules/*/tests` automatically, but `testpaths`
keeps a bare `uv run pytest` honest.

## 7. Add it to CI and the release matrix

In `.github/workflows/ci.yml`, add a pytest step:

```yaml
      - name: Run pytest (orders)
        run: cd modules/orders && uv run pytest
```

In `.github/workflows/release.yml`, add it to the `publish-pypi` matrix —
**this is what actually publishes it**:

```yaml
        package:
          - simple_module_pagebuilder
          - simple_module_orders
```

## 8. Install and migrate

```bash
make install
make migration msg="add orders"
```

Open the generated revision and add the branch label under the identifiers:

```python
branch_labels = ("orders",)
```

Then read the rest of the file — confirm it creates your tables and drops
nothing — and apply it:

```bash
make migrate
```

## 9. One-time PyPI setup

Before the first release, create the project on
<https://pypi.org/manage/account/publishing/> with the field values in the
header comment of `.github/workflows/release.yml`. No API token is needed;
publishing uses OIDC trusted publishing.

## 10. Verify

```bash
make lint
make test-py
make build
```

`make lint` covers metadata, README, hardcoded strings, file size, and version
sync — the four things most likely to be wrong on a fresh module.
