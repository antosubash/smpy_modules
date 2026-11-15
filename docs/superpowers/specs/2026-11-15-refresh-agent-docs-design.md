# Refresh AGENTS.md, CLAUDE.md and README — design

## Goal & scope

Bring the three entry-point docs in line with the repo after the 2026-11-11
review batches (#362–#380), and make them maintainable:

- **AGENTS.md (new)** becomes the one agent guide, readable by any coding agent
  (Codex reviews every PR here and reads `AGENTS.md`, not `CLAUDE.md`).
- **CLAUDE.md** becomes a thin file: `@AGENTS.md` (Claude Code's import) plus
  the few Claude-Code-only notes (the `running-the-stack` skill, worktree shell
  rules). No content duplicated between the two.
- **README.md** is corrected and completed for humans.

Out: rewriting module docs beyond moving facts into them (below); CHANGELOG
entries (docs-only change); `docs/plans/`, `docs/superpowers/` history.

## Approach

AGENTS.md is a **restructure, not a copy**: today's CLAUDE.md (578 lines) is a
log of one bold paragraph per change. The new file is organised by what an
agent needs, ~250–300 lines:

1. What this repo is, and the module list (all **eight**: ai, analytics,
   billing, images, news, newsletter, pagebuilder, records).
2. **Checks**: one table of every `make lint` step (15, incl. basedpyright,
   `check_ts_imports`, `check_sibling_contracts` boundary, `check_metadata`,
   `check_readmes`, `check_hardcoded_strings`) and the CI jobs (3.12/3.14
   matrix, Postgres per module, Docker build + boot, bg-tasks, e2e shards and
   the three opt-in jobs, nightly framework-latest, weekly images-models).
3. **Cross-module rules** (kept in full, they are the ones that bite): pins and
   floors, contracts-only boundary (Python and TS), migrations + one head +
   framework porting rule, tenant binding + fail-closed guard (incl. analytics,
   which binds but has no guard), DB-backed settings / no env reads (incl.
   analytics) + the stored-secret crypto family and `SealedSecret`, billing's
   `finalize_session`, host settings precedence, CSP nonce, page language,
   `pages/` rule, lockstep releases, 300-line cap, moved paths until 0.0.17
   (with the removal checklist), background work through `background_tasks`,
   e2e specs stand alone.
4. **Per-module invariants**: one or two lines each plus a link to the module
   doc that holds the detail (newsletter's ~90 lines, records submissions,
   billing subjects, images plugins, ai env reads).
5. Local setup (DB, dev-services, workers/eager), unreleased framework, i18n
   (the module key-tree trap stays; fixed to eight modules, 182-line ref).
6. Pointers: SECURITY.md, CHANGELOG.md, docs/module-layout.md,
   docs/adding-a-module.md, docs/releasing.md, docs/secret-key-rotation.md;
   `docs/plans/`, `docs/superpowers/` and dated `*-2026-*` reports are history.

Rejected: (a) keep CLAUDE.md and symlink AGENTS.md → it, because two names for
one 578-line log fixes nothing and symlinks break on Windows checkouts; (b)
leave CLAUDE.md as is and only add AGENTS.md, because the two would drift.

**Nothing is dropped, only moved.** Before a paragraph shrinks to a pointer,
its facts must already be in the module doc; the audit found gaps, which get
added first: `forget_deliveries`, `SealedSecret` (records), `PlanOut`
(billing), `clear_for_confirmation`, `host_tenant`, `UserDirectory` /
`tenant_member_ids` (newsletter), `metering._own_factory` (ai). The per-version
framework-port narrative (0.0.40 token hashing, 0.0.41–0.0.44 revision ids,
labels dropped) moves to a new `host/migrations/README.md`, which AGENTS.md
links; the rule stays.

## README changes

Modules table gains **ai** and analytics' PyPI link; Layout tree lists all
eight modules, `docs/`, `docker/`, compose files, four workflows, SECURITY.md,
CHANGELOG.md; Quick start: prerequisites (uv, Python 3.12, Node 26), `make
install` (incl. `sync-module-deps`, no `anonymize` extra), `make env` (three
generated secrets, no-op if `.env` exists), workers vs eager; Docker: Python
3.14 runtime, uid 10001, `/health/live`, compose's in-process task settings,
link to secret-key rotation; Testing: `test-js`, `e2e-bundle`, `e2e-parallel`,
full lint list (basedpyright), the CI job list; Adding a module: the real
checklist in short, pointing at a refreshed `docs/adding-a-module.md`;
Releasing: `version` input, green-CI gate, CHANGELOG; unreleased framework:
also links `branding`; Conventions: ruff incl. `S`, contracts-only boundary,
`check_ts_imports`, `# floor:` comments; link SECURITY.md.

## Decisions made (override any at approval)

- AGENTS.md is canonical; CLAUDE.md imports it with `@AGENTS.md`.
- `docs/adding-a-module.md` is refreshed in the same PR (README points at it
  and the audit found it stale).
- Code comments in `scripts/` and `.github/` that cite "CLAUDE.md" for a rule
  are repointed to AGENTS.md; migration revisions keep theirs (history).
- No new check script for doc links; verification is a one-off script run in
  this PR (every path and `make` target named in the three files exists).

## Testing

`make lint` (`check_readmes`, `check_rules` tests that may read these files),
`scripts/tests` and `host/tests`; a one-off link/path check over AGENTS.md,
CLAUDE.md, README.md and the touched docs; Codex reviews the PR for factual
accuracy against the code. No QA (docs only).

## Risks

A rule lost in the restructure. Mitigation: a checklist of every bold
paragraph in the old CLAUDE.md mapped to its new home, reviewed by Codex.
