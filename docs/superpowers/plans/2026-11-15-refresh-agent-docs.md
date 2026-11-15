# Refresh AGENTS.md, CLAUDE.md and README — plan

Design: `docs/superpowers/specs/2026-11-15-refresh-agent-docs-design.md`.

| # | Task | Files | Done when | Parallel |
|---|---|---|---|---|
| 1 | Fill module-doc gaps; move framework-port history | `modules/{records,billing,newsletter,ai}/docs/*.md`, new `host/migrations/README.md` | each identifier (`forget_deliveries`, `SealedSecret`, `PlanOut`, `clear_for_confirmation`, `host_tenant`, `UserDirectory`/`tenant_member_ids`, `metering._own_factory`) appears in its module doc with the rule CLAUDE.md states; the 0.0.40–0.0.44 port narrative is in `host/migrations/README.md` | with 2 |
| 2 | README + `docs/adding-a-module.md` | `README.md`, `docs/adding-a-module.md` | every audit finding addressed; every path/target named exists | with 1 |
| 3 | AGENTS.md + thin CLAUDE.md (hard) | `AGENTS.md`, `CLAUDE.md` | mapping table: every bold paragraph of the old CLAUDE.md → its new home (AGENTS.md section or module doc); ~250–300 lines | after 1 |
| 4 | Repoint rule citations | comments in `scripts/`, `.github/` naming CLAUDE.md | `grep` shows only migrations and history docs still cite CLAUDE.md for rules | after 3 |
| 5 | Verify | — | one-off path/target check passes; `make lint`, `scripts/tests`, `host/tests` pass | last |
