# Releasing

Releases are **lockstep**: every module in the repo shares one version, and one
release publishes all of them. A module that hasn't changed still gets a new
version. That's the trade — it's simpler to reason about than per-module
versioning, and it matches how `simple_module_python` itself releases.

## Running a release

Actions → **release** → *Run workflow*, **on `main`**. Pick either:

- **bump** — `patch` (default), `minor`, or `major`, applied to the version in
  the root `pyproject.toml`.
- **version** — an explicit value like `0.2.0`, which overrides `bump`.

That's the whole process. The release refuses to start unless CI is green on
the commit it would ship, and waits for CI if it is still running.

## What the four jobs do

| Job | Does |
|---|---|
| `resolve` | Computes the version (from `bump` or `version`) and validates its format, and lists the module packages to publish from `modules/*/pyproject.toml`. Then the gates: the run must be on `main`; `v<version>` must not already be tagged and `release/v<version>` must not exist; and every ci.yml `push` (or manual) run on the dispatched commit must, as its latest attempt, have concluded `success` — not only the newest, so a failed re-run of an older run is never outvoted by a green one (`scripts/release_ci_gate.py`). A run still in progress is waited for, up to 70 minutes; a failed or cancelled one (a pending run is cancelled when a newer one queues behind it) is cleared by re-running it to green. Every later job reads this job's outputs, so the version is decided exactly once. |
| `build` | Commits the bump (versions + `uv lock`) on top of the dispatched commit, builds the module frontends and `uv build --all-packages` from that commit with no dependency cache, records the sha256 of every artifact as a job output, uploads them, and only then pushes the commit to the staging branch **`release/v<version>`**. |
| `publish-pypi` | One matrix job per module. Downloads this run's artifact and verifies it against `build`'s sha256 manifest (same files, same hashes, nothing extra), selects that module's artifacts, checks that any of them PyPI already has for this version are byte-identical (sha256, `scripts/release_pypi_check.py`), and publishes via OIDC trusted publishing with `skip-existing`, so a retry skips files that already landed. `fail-fast: false`, so one failure doesn't cancel the others. |
| `finalize` | Tags the staged commit `v<version>`, lands the bump on `main`, creates the GitHub release, and deletes the staging branch. |

Only one release runs at a time (`concurrency: release`).

### Why the bump is staged before publishing (#115)

PyPI never takes a version back. Previously the bump commit and tag were
created *after* publishing and pushed to `main` atomically; if anything merged
to `main` while the release ran, that push was rejected and the version sat on
PyPI with no commit or tag, and re-running could not help because PyPI refuses
the same version twice.

Now the exact commit the artifacts were built from reaches origin — on a new
branch, so nothing can reject it — before any upload. After publishing:

- **The tag** points at that staged commit, so `v<version>` is always the
  source of what is on PyPI. Pushing a new tag cannot race with `main`.
- **`main`** is fast-forwarded to the staged commit when nothing landed in the
  meantime (the usual case: the tag is then on `main`'s history). When `main`
  moved, the bump is *re-applied* on top of the new `main` — `bump_version.py`
  plus `uv lock`, both deterministic — rather than rebasing the staged commit,
  whose `uv.lock` would conflict with any dependency change. That commit's
  message names the tagged one. The push is retried, never forced.

**`uv.lock` on a moved `main`.** The re-applied commit's `uv lock` resolves
against the new `main`, so its lockfile can differ from the staged one — any
dependency change merged meanwhile is in it. That is the lock `main` should
have; the tag and the published artifacts still record exactly what was built.

### If something fails

| Where | State | What to do |
|---|---|---|
| `resolve` | Nothing happened. | Fix the cause (wait for or fix CI; for a commit with no CI run, such as the bot's own release commit, run **CI** by hand with *Run workflow*) and dispatch again. |
| `build`, before staging | Nothing reached origin or PyPI. | Fix and dispatch again with the same version. |
| `publish-pypi`, every package | `release/v<version>` exists; nothing on PyPI. | Fix the cause and **Re-run failed jobs** — the same artifacts are published and `finalize` runs. To abandon the version instead, delete `release/v<version>`. |
| `publish-pypi`, some packages or files | Some packages — or one file of a package, say its wheel but not its sdist — are on PyPI. | **Re-run failed jobs** once the cause is fixed: the published packages are not retried, and inside a retried one the files PyPI already has are skipped after their sha256 is checked against this build. Do not dispatch a fresh run — its build would produce different artifacts for the version some packages already carry. |
| `publish-pypi`, "different sha256" | PyPI holds a file for this version that this run did not build. | Nothing this run can fix: the version is taken. Delete `release/v<version>` and release the next version. |
| `finalize` | Packages are on PyPI; the staged commit holds their source. | **Re-run failed jobs.** Each step checks what already happened (tag present on the staged commit, `main` already at the version, release already created), so a re-run picks up where it stopped. |

A version that is fully on PyPI but whose `finalize` cannot complete (say
`main` refuses pushes from Actions) is still tagged once the tag step has run;
bumping `main` by hand to that version is then the only step left.

## Supply chain

- **What reaches PyPI is what `build` built.** `build` writes the sha256 of
  every artifact (and of the PyPI check script, which travels with them so
  `publish-pypi` checks out nothing) into a job output. `publish-pypi`
  downloads this run's artifact and refuses to upload unless every file
  matches and none was added. Nothing is rebuilt after `build`; `finalize`
  tags only a staged commit whose parent is the CI-verified SHA.
- **No caches in a release.** Caches are shared across workflows, and ci.yml
  runs for pull requests, so a release restores none: every `setup-uv` in
  `release.yml` has `enable-cache: false` (its default caches on hosted
  runners), `setup-node` has `package-manager-cache: false` (it caches npm on
  its own when `package.json` names a package manager), and there is no
  `actions/cache`. `build` installs fresh with `uv sync --locked` and
  `npm ci`. Likewise `framework-latest.yml` (which resolves versions no
  lockfile vetted) saves none, so the nightly run can never feed ci.yml or a
  release. It has `contents: read` only and uploads no artifacts.
- **Actions are pinned to commit SHAs** in `release.yml`, the tag in a
  comment; Dependabot moves both together.

## One-time PyPI setup, per module

At <https://pypi.org/manage/account/publishing/>, add a pending publisher:

| Field | Value |
|---|---|
| PyPI project name | `simple_module_<name>` |
| Owner | `antosubash` |
| Repository name | `smpy_modules` |
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

The `publish-pypi` matrix is built by the `resolve` job from every
`modules/*/pyproject.toml`, so a new module is published without editing
`.github/workflows/release.yml`. It still needs one-time PyPI Trusted
Publishing setup, or its publish job fails. See
[adding-a-module.md](adding-a-module.md).
