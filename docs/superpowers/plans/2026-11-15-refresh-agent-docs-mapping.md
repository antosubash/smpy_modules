# Old CLAUDE.md → new homes (review artifact)

Every section and bold-lead paragraph of the old `CLAUDE.md`
(`git show 5c07822d:CLAUDE.md`, 578 lines) and where its content lives after
task 3. "AGENTS § X" is a section of `AGENTS.md`. A paragraph that held several
rules is split into rows. Lines are the old file's.

| # | Old (line) | Content | New home |
| --- | --- | --- | --- |
| 1 | Intro (1–4) | Guidance for Claude Code, README for general docs | AGENTS intro; `CLAUDE.md` now `@AGENTS.md` + Claude Code notes |
| 2 | § What this repo is (6–10) | Distributable add-ons, PyPI names, host never published | AGENTS § What this repo is (now lists all nine modules, events included) |
| 3 | **Pin policy differs by role** (14–22) | Ranges in modules, `==` in host, `check_rules.py`, `# floor:` comments, floor not compared with lockstep | AGENTS § Dependencies; `check_rules.py` row in § Checks |
| 4 | same (23–28) | `check_sibling_contracts.py` floor/tag rule, next-release exception, needs tags | AGENTS § Dependencies ("The floor must ship what you import"); § Checks (`git fetch --tags`) |
| 5 | same (29–32) | Contracts-only boundary, `BOUNDARY_ALLOWLIST` empty (#336) | AGENTS § Module boundaries |
| 6 | **Migrations live in `host/migrations/versions/`** (34–46) | Rule, `branch_labels`, `<module>@base` walks everything | AGENTS § Migrations (rule); detail, 20-downgrade evidence, upstream #333 closure → `host/migrations/README.md` § Rules |
| 7 | **The history must end in exactly one head** (48–55) | Merge revision, `check_migration_heads.py`, `upgrade heads` hides split, name the parent | AGENTS § Migrations + § Checks; example ids `52ce60faa542`, `d3a2801784b0` → `host/migrations/README.md` § Rules |
| 8 | **Framework tables are this host's to migrate too** (57–61) | Port unchanged, `alembic check` SQLite + Postgres | AGENTS § Migrations; `host/migrations/README.md` § Rules |
| 9 | same (61–82) | Per-release port log: 0.0.37/38 ids, 0.0.41 bg-tasks/sharing/file-storage tables, 0.0.40 token hashing, 0.0.42 dropped `file_storage` label, 0.0.43/44 ids, audit_log/oidc not ported, `e731a1b2c3d4` case check | `host/migrations/README.md` § Framework revisions ported; AGENTS § Migrations links it (rule "drop a duplicate label" kept in AGENTS) |
| 10 | same (83–87) | `env.py` ignores SQLite's false index change | `host/migrations/README.md` § Rules ("`env.py` ignores one false change"); AGENTS § Migrations points to it |
| 11 | **Since 0.0.44 most framework modules follow the module layout** (88–92) | New import paths, raise the floor, `test_host_boots.py` | AGENTS § Framework behaviour to code against |
| 12 | **Since 0.0.43 the production CSP is nonce-based** (93–98) | Nonce, no eval, Inertia 409, ETag/no-store, `data-page` | AGENTS § Framework behaviour to code against |
| 13 | same (99–102) | SQLModel unpinned, bare `datetime` is `timestamptz`; `9d83e789a5b4` retype | AGENTS § Framework behaviour (rule); revision id → `host/migrations/README.md` (0.0.37/0.0.38) |
| 14 | same (102–105) | Soft-delete/tenant criteria reach Core statements, `include_deleted=True` | AGENTS § Framework behaviour to code against |
| 15 | **A page's language is fixed for its lifetime** (107–113) | Whole paragraph | AGENTS § Content language |
| 16 | **Every … entry point binds a tenant** (115–122) | Mixin filters only while bound; fail-closed guard, `TenantUnbound`, `all_tenants(stmt)`, Core/`text()` predicate | AGENTS § Tenancy (now also analytics: binds, no guard, explicit predicates) |
| 17 | same (122–130) | `bind_admin`/`bind_public`, the single/multi/none rule, upstream wins, never shareable-cached | AGENTS § Tenancy |
| 18 | same (131–140) | Per-module tenancy copies, scheduler/Celery per tenant, newsletter via `subscription_list_tenants`, billing via `billing_context` | AGENTS § Tenancy ("Copies, not imports", "Background work runs per tenant") |
| 19 | same (140–145) | Pagebuilder read only via contracts, caller names tenant; bundle sections | AGENTS § Module boundaries |
| 20 | **Records' website-submission routes are anonymous writes** (147–153) | Type is trust anchor, `system=`, no `RequiresCsrf` on purpose | AGENTS § Per-module invariants (records); detail `modules/records/docs/architecture.md#public-submissions-and-system-fields`, `api-reference.md#website-submissions` |
| 21 | same (153–159) | Every purge through `forget_deliveries`; retention sweep soft- then hard-deletes | AGENTS § Per-module invariants (records); `modules/records/docs/architecture.md#every-purge-forgets-its-delivery-claims` and "The form on the page" (retention) |
| 22 | **Newsletter content and test sends** (161–169) | `content.render` only, allow-list re-serialise, cards via `content/integrations/`, SMTP change clears password, `expected_revision`, list access re-check | AGENTS § Per-module invariants (newsletter, one line); `modules/newsletter/docs/content.md`, `index.md` § Settings (password clear) |
| 23 | same (169–186) | Test-send lock and budget, vouched-for recipients (`UserDirectory`, `tenant_member_ids`, extras), `suppressed`, `normalise_email`, `records_form`, `outcome`+`code` | AGENTS § Per-module invariants (one line); `modules/newsletter/docs/sending.md#test-sends`, `audience.md` (hashes), `content.md#test-send` |
| 24 | same (186–190) | Content links vs `public_base_url`, `/newsletter/brand/logo` | `modules/newsletter/docs/content.md` § URLs, § Footer and branding |
| 25 | **Newsletter mirrors records' unsubscribes** (192–209) | Handler + hourly reconcile, tenant-wide, only DOI clears, lift rules, `lock_confirmation`, audience frozen at schedule | AGENTS § Per-module invariants (newsletter suppressions); `modules/newsletter/docs/audience.md#suppressions`, `sending.md` § The render snapshot / § Freeze |
| 26 | **The Mailchimp import never clears…** (211–233) | All seven bullets (records `import_subscribers`, `refresh=False`, `opted_out_anywhere`, lock order, staging/slices, no events, `POST /lists`, dispatch hook) | AGENTS § Per-module invariants (one line); `modules/newsletter/docs/import.md`, `modules/records/docs/api-reference.md` (`lock_import_batch`), `modules/newsletter/docs/operations.md#the-dispatch-hook-e2e-only` |
| 27 | **Never add a file under `pages/`…** (235–240) | Whole paragraph | AGENTS § Layout and size |
| 28 | **Releases are lockstep** (242–246) | Whole paragraph | AGENTS § Background work, releases, e2e; `--check-current` in § Checks |
| 29 | **`billing` commits … `finalize_session`** (248–259) | `test_commit_sites.py`, `RequestSession`/`on_commit`, metering transactions, `db=` | AGENTS § Per-module invariants (billing); `modules/billing/docs/architecture.md#transactions--the-rule-that-bites`, § Transaction rules |
| 30 | same (260–265) | `subject_mode = user`, images bills `user:<owner>`, subject per hold replayed | AGENTS § Per-module invariants (billing); `modules/billing/docs/subjects.md` § Images bills the collection's owner |
| 31 | same (266–270) | Webhooks never trusted (`resync`/`apply_snapshot`), `PlanOut` no input bounds | AGENTS § Per-module invariants (billing); `modules/billing/docs/architecture.md` § From Stripe to local state, § Response models do not inherit input bounds |
| 32 | **… read no environment variables for their settings** (272–282) | DB-backed settings, no env sources, `on_startup` reads, `_RESTART` | AGENTS § Settings and the environment (now "all eight", incl. analytics) |
| 33 | same (283–289) | Newsletter `smtp_password` storage, endpoint, workers refuse plaintext, `manage_url` | AGENTS § Per-module invariants (newsletter SMTP); `modules/newsletter/docs/operations.md#the-secret`, `index.md` § Settings; `crypto.is_encrypted` rule in AGENTS § Stored secrets |
| 34 | same (290–298) | ai SYSTEM scope, its three env reads, `metering._own_factory`, images passes its factory | AGENTS § Per-module invariants (ai); `modules/ai/docs/operations.md` § Settings (three subsections) and § Secret key rotation |
| 35 | **Stored secrets rotate with `SM_SECRET_KEY_PREVIOUS`** (299–308) | Crypto parity family, formats, previous keys, reencrypt TARGETS, signed things not covered | AGENTS § Stored secrets; `docs/secret-key-rotation.md` |
| 36 | **Records' captcha secret never stored in the clear** (309–315) | `SealedSecret`, json dump, `register_settings`, startup seal, fail closed | AGENTS § Per-module invariants (records secret fields); `modules/records/docs/operations.md#website-forms-and-newsletters` |
| 37 | same (315–317) | Images workers read `settings_for(ImagesSettings, …)` | AGENTS § Settings and the environment |
| 38 | **Newsletter campaigns are sent only by the `newsletter.dispatch` beat** (319–332) | Lock per slice, attempt row before SMTP, snapshot; `/u/` `/o/` `/c/` token rules, `host_tenant`, click redirect, no IP/UA, `5.1.x` | AGENTS § Per-module invariants (newsletter sending) and § Tenancy (exceptions); `modules/newsletter/docs/sending.md` § The dispatcher / § Unsubscribe / § Verdicts, `tracking.md` |
| 39 | **Images plugins from `images_extensions.py`** (334–343) | Whole paragraph | AGENTS § Per-module invariants (images); `modules/images/docs/writing-a-plugin.md#registration` |
| 40 | **Host settings come from the environment first** (345–366) | `merge_host_settings`, precedence, `.env` wins, restart fields, per-request fields, boot failure outside dev/testing | AGENTS § Settings and the environment |
| 41 | same (366–374) | Headless scripts never provision `host.secret_key` | AGENTS § Settings and the environment |
| 42 | **Run Python entry points from the repo root** (376–379) | Whole paragraph | AGENTS § What this repo is |
| 43 | **Module layout** (381–388, 393–394) | Package root, areas, tests mirror, moves-only boundary | AGENTS § Layout and size; `docs/module-layout.md` |
| 44 | same (389–392) | TS imports only via `@simple-module-py/<module>`, `check_ts_imports.py` | AGENTS § Module boundaries; § Checks |
| 45 | **Paths moved in 0.0.14 stay importable until 0.0.17** (396–414) | Hooks, stubs, `--check`, the full removal checklist incl. pagebuilder `exports`, `styles.css`, `ALLOWLIST` | AGENTS § Paths moved in 0.0.14 (checklist kept item for item) |
| 46 | **300-line cap** (416–422) | Cap, 280 warning, `Protocol` hosts | AGENTS § Layout and size; § Checks |
| 47 | **Pyright checks only its include list** (424–432) | basedpyright scope, `sqlmodel.col()`, ignores, ruff `S` | AGENTS § Checks (ruff and basedpyright rows) |
| 48 | **Every e2e spec file stands alone** (434–447) | Sharding, seeding, `start-test-server.sh`, `e2e-parallel`, newsletter opt-in | AGENTS § Background work, releases, e2e |
| 49 | § Local database (449–456) | SQLite default, Postgres URL | AGENTS § Local setup |
| 50 | **Prefer the shared `dev-services` stack** (458–463) + `docker run` (465–469) | Whole paragraphs | AGENTS § Local setup |
| 51 | Redis and Celery (471–477) | Workers, make targets, eager mode | AGENTS § Local setup |
| 52 | same (477–479) | Only `bg-tasks` CI job runs non-eager; new work via `background_tasks` | AGENTS § Background work, releases, e2e |
| 53 | same (479–487) | tippecanoe; `--no-extra anonymize` everywhere, which jobs sync what, fake detector | AGENTS § Local setup (install) and § Per-module invariants (images) |
| 54 | same (487–492) | `images-models` only; **no AGPL**, MIT models, no torch/ultralytics | AGENTS § Per-module invariants (images); § Checks (`images-models.yml`); `modules/images/docs/index.md#anonymize-models-and-licences` |
| 55 | § Working against an unreleased framework (494–503) | Whole section | AGENTS § Working against an unreleased framework |
| 56 | § Known deferred work (505) | Heading | dropped: nothing in it is deferred any more (i18n is done; its contents moved, rows 57–62) |
| 57 | **UI i18n — done** (507–522) | Catalogues, `check_locales.py`, host locales, `set-locale`, `ui` catalogue, overrides test | AGENTS § i18n (console UI, host chrome); "All seven" fixed to every (eight) module; `host/locale_switch.py` gone (history) dropped |
| 58 | same (524–531) | `t(keys…)` with no `defaultValue`, runtime families, namespace = directory | AGENTS § i18n |
| 59 | **The trap, if you add a module** (533–545) | npm package lacks module keys; `gen-i18n` not enough | AGENTS § i18n ("The trap when adding a module") |
| 60 | same (547–553) | Derive keys from `en.json`, news reference | AGENTS § i18n; "about ninety lines" fixed to 182 |
| 61 | same (555–565) | Puck labels hold keys; content i18n vs console | AGENTS § i18n |
| 62 | **The demo host defaults to single-tenant** (566–578) | Single-tenant default; multi-tenant, billing-user and newsletter e2e opt-ins | AGENTS § Local setup (tenancy) and § Background work, releases, e2e (the three opt-ins, newsletter once) |

## Summary

- 62 rows covering the five sections (the "Rules that are easy to get wrong"
  heading is now AGENTS § Cross-module rules), all 31 bold-lead paragraphs and
  the unbolded paragraphs between them.
- Kept in AGENTS.md as rules: 44 rows (the cross-module rules in full, the
  Checks table, local setup, unreleased framework, i18n).
- Shortened to a one- or two-line rule plus a link to a module doc: 15 rows
  (records 20, 21, 36; newsletter 22–26, 33, 38; billing 29–31; images 39; ai 34).
- Moved to `host/migrations/README.md`: the per-release port log and the
  `env.py` exception (rows 9, 10, parts of 6, 7, 13).
- Dropped: the "Known deferred work" heading (stale: nothing is deferred), the
  duplicated newsletter e2e paragraph (it appeared twice, rows 48 and 62; kept
  once), "All seven" and "about ninety lines" (stale facts, corrected), the
  history notes "a bare `Settings()` read the environment only, before #260"
  and "the host's copy, `host/locale_switch.py`, is gone" (history, no rule), and
  the list of extras `--all-extras` installs (`quality`, `ai`, `billing`,
  `pagebuilder`; implied by the flag).

## Added on main since `dda286dd` (`git diff dda286dd origin/main -- CLAUDE.md`)

Merged after framework 0.0.47 and the events module landed. "AGENTS § X" is a
section of `AGENTS.md`; "events rules" is `modules/events/docs/rules.md`
(new, the contributor rules the other events pages did not state).

| # | Main added or changed | New home |
| --- | --- | --- |
| A1 | Host pin `==0.0.44` → `==0.0.47` | AGENTS § Dependencies |
| A2 | 0.0.46 `e480d7dd348f`; `0a30d2baa903` stays as shipped; `c7a41e9d2b60` SQLite-only retype (`AwareDateTime`, 0.0.45) | `host/migrations/README.md` § Framework revisions ported (0.0.45, 0.0.46); AGENTS § Migrations points at it |
| A3 | `make_include_object` replaces the `env.py` `tenant_browse` workaround | `host/migrations/README.md` § Rules ("The SQLite index check is the framework's"); AGENTS § Migrations pointer reworded |
| A4 | Flat paths gone since 0.0.46 | AGENTS § Framework behaviour to code against; `docs/adding-a-module.md` |
| A5 | 0.0.45 second `Content-Security-Policy` kept beside the app policy; news and pagebuilder `public_csp` defaults | AGENTS § Framework behaviour to code against |
| A6 | Events joins the tenancy rule (six guards, `sm_events.core.tenancy` copy of newsletter's) | AGENTS § Tenancy (entry points, guard, copies, background work) |
| A7 | Events access `POLICY`, share picker, names, `claim_revision`, recurrence, sanitisers, wall clock + IANA zone, durable bus events | AGENTS § Per-module invariants (events, one line); events rules § Access |
| A8 | FullCalendar adapter rules | AGENTS § Per-module invariants; events rules § The calendar |
| A9 | Public gate `core/access/public.py`, `leaks.py`, feeds, JSON-LD, `public_base_url`; cards contract and blocks | AGENTS § Per-module invariants; events rules § The public surface |
| A10 | Worker and beat, `events` queue, `core/worker.py` parity copy | AGENTS § Local setup (Workers), § Per-module invariants; events rules § Worker and beat |
| A11 | Registration seats, lock order, registration token, submit bounds, "My registrations" | AGENTS § Per-module invariants (records, registration), § Tenancy exceptions; `modules/records/docs/registration.md` § For contributors (new) |
| A12 | Private feeds and the `.ics` import (third token-bound route) | AGENTS § Tenancy exceptions and § Per-module invariants; events rules § Private feeds and the .ics import |
| A13 | Subscriptions fetch, `url_enc`, `Policy`, `fetch_wait`, `target_gate`, `seed_external` | AGENTS § Per-module invariants and § Stored secrets; events rules § Subscriptions |
| A14 | Reminders at most once | AGENTS § Per-module invariants; events rules § Reminders are at most once |
| A15 | Records' `contracts.dated` | AGENTS § Per-module invariants (records, registration); `modules/records/docs/registration.md` § For contributors |
| A16 | Newsletter event cards (`sm_events.contracts.cards`, snapshot, frozen at scheduling) | AGENTS § Per-module invariants (newsletter); already stated in `modules/newsletter/docs/content.md` § Event cards |
| A17 | No-environment-variables rule includes events; `SM_SECRET_KEY_PREVIOUS`, `SM_SECRET_KEY` fallback | AGENTS § Settings and the environment |
| A18 | Stored-secret crypto: five copies, `COLUMN_TARGETS`, `events_subscription.url_enc` | AGENTS § Stored secrets |
| A19 | `events_extensions.py` plugin loader | AGENTS § Per-module invariants; events rules § Plugins |
| A20 | e2e: `newsletter-events.spec.ts` under `E2E_NEWSLETTER=1` | AGENTS § Background work, releases, e2e |
| A21 | Redis/Celery users and `make worker` queues | AGENTS § Local setup (Workers) |
| A22 | i18n: "All nine", events calls `t(keys.…)` | AGENTS § i18n |
