# Releasing

Releases are **lockstep**: every module in the repo shares one version, and one
release publishes all of them. A module that hasn't changed still gets a new
version. That's the trade — it's simpler to reason about than per-module
versioning, and it matches how `simple_module_python` itself releases.

## Running a release

Actions → **release** → *Run workflow*. Pick either:

- **bump** — `patch` (default), `minor`, or `major`, applied to the version in
  the root `pyproject.toml`.
- **version** — an explicit value like `0.2.0`, which overrides `bump`.

That's the whole process. Nothing is tagged or committed until every package
has published.

## What the four jobs do

| Job | Does |
|---|---|
| `resolve` | Computes the version (from `bump` or `version`) and validates its format. Every later job reads this one output, so the version is decided exactly once. |
| `build` | Bumps versions **in the working tree only**, builds the module frontends, then `uv build --all-packages`. Uploads the artifacts. No commit. |
| `publish-pypi` | One matrix job per module. Selects that module's artifacts and publishes via OIDC trusted publishing. `fail-fast: false`, so one failure doesn't cancel the others. |
| `finalize` | Re-applies the bump, commits, tags `v<version>`, pushes, and creates the GitHub release. |

The ordering matters: the tag reaches origin only after every publish
succeeds, so a failed build never strands an orphan tag you have to clean up.

## If a publish fails partway

Nothing was committed or tagged, so there is no cleanup on the repo side. Fix
the cause and re-run the workflow with the **same explicit version**.

The one thing you cannot redo is a version that already uploaded to PyPI —
PyPI rejects re-uploads of an existing version. If module A published and
module B failed, re-running the same version will fail on A. Release the next
patch version instead.

## One-time PyPI setup, per module

At <https://pypi.org/manage/account/publishing/>, add a pending publisher:

| Field | Value |
|---|---|
| PyPI project name | `simple_module_<name>` |
| Owner | `antosubash` |
| Repository name | `simple_module_python_modules` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Then in GitHub: Settings → Environments → `pypi`. Add required reviewers there
if you want a manual approval gate before anything is published.

No API token exists anywhere — publishing authenticates over OIDC.

## The version-bump script

`scripts/bump_version.py` rewrites `project.version` in the root
`pyproject.toml` and in every `modules/*/pyproject.toml` and
`modules/*/package.json`.

It deliberately does **not** touch dependency specifiers. The framework repo's
version of this script rewrites every `simple_module_*` requirement to
`==<version>`; run here, that would turn `simple_module_core>=0.0.35,<0.1`
into a pin on a *this-repo* version number that no framework release has.
`scripts/tests/test_bump_version.py` guards it, and CI runs
`--check-current` so drift between manifests fails the build.

```bash
uv run python scripts/bump_version.py 0.2.0 --dry-run   # preview
uv run python scripts/bump_version.py --check-current   # verify sync
```

Module code never hardcodes its version: `ModuleMeta.version` reads
`importlib.metadata.version(...)`, so the bump can't leave it behind.

## Adding a module to releases

New modules are **not** published until they appear in the `publish-pypi`
matrix in `.github/workflows/release.yml`. See
[adding-a-module.md](adding-a-module.md).
