# pagebuilder tenancy (#38) — design

## Goal & scope

Make every pagebuilder table tenant-owned so one host can serve several sites,
with anonymous visitors resolved to a tenant by subdomain and fail-closed
(404, never 500, never another tenant's content) when none resolves.

**In:** `MultiTenantMixin` on all nine tables, tenant-prefixed unique indexes,
a host migration backfilling `"default"`, per-request tenant binding (admin +
public), a tenant-looping scheduler, per-tenant media and snapshot-blob
directories, an explicit cross-tenant orphan-media scan, tests.

**Out:** the domain resolver itself (framework 0.0.35 already ships it:
`tenants.host_resolver`, `subdomain_base`), custom domains (not in the
framework), turning multi-tenant on in the demo host (blocked by news, see
CLAUDE.md), cross-tenant snapshot transfer.

## Approach

Copy records' proven model (`docs/plans/2026-09-23-records-multitenancy.md`),
minus what pagebuilder doesn't need:

- **Mode** is read off the built middleware stack (same rule as records):
  no `TenantMiddleware`, or one `fixed` to `"default"` → `SINGLE`; otherwise
  `MULTI`. A host pinned to a different `default_tenant` is refused at
  startup, exactly as records does — the migration backfills `"default"`.
- **SINGLE**: every entry point binds `"default"`. Behaviour is unchanged for
  today's hosts.
- **MULTI**: entry points bind the tenant the framework resolved
  (`request.state.tenant_id` — subdomain for visitors, membership/session for
  members). Admin with no tenant → 403; public with no tenant → 404.

Binding is a yield dependency placed **first** on every pagebuilder router, so
`get_db`'s commit runs inside the scope.

Rejected: (a) relying on `TenantMiddleware` alone — on a single-tenant host
with no `default_tenant` nothing is bound and writes fail `NOT NULL`;
(b) an exception handler mapping `MissingTenantError` → 404 — it would also
hide real bugs in admin code as 404s.

## Design

**Models** (all gain `MultiTenantMixin`): `Page`, `PageRevision`,
`PageRedirect`, `MediaAsset`, `Layout`, `LayoutRevision`, `ContentSnapshot`,
`SnapshotMedia`, `PendingImport`. Unique indexes become:

| was | becomes |
|---|---|
| `(locale, slug)` | `(tenant_id, locale, slug)` |
| `(translation_group, locale)` | `(tenant_id, translation_group, locale)` |
| redirects `(locale, from_slug)` | `(tenant_id, locale, from_slug)` |
| `MediaAsset.filename unique` | `(tenant_id, filename)` |
| pending import partial `(status) WHERE PENDING` | `(tenant_id, status) WHERE PENDING` |

SM024 must report nothing for pagebuilder.

**Migration** (`host/migrations/versions/`): add `tenant_id` (`VARCHAR(50)`,
backfilled `'default'`, then `NOT NULL`, indexed) to the nine tables; drop and
recreate the five unique indexes. SQLite path via `batch_alter_table`, as
`4ecb931245dd_records_tenant_id.py` does. Must pass `alembic check` and the
CI downgrade/upgrade round-trip.

**Layout** stays "get-or-create", now per tenant (the read is tenant-filtered,
so it can never fall back to another tenant's row).

**Public surface** (`/p/{slug}`, `/{locale}/p/{slug}`, `/sitemap.xml`): bound
by `bind_public`; no tenant → the same 404 as an unknown slug. Redirects,
`public_claims`, layout and alternates all run inside that scope.
`public_claims` keeps its signature; its docstring states that claims are
called inside the request's tenant scope and must stay within it (there are no
registrants today).

**Media**: files live at `media_root/<tenant_id>/<filename>`, URLs are
`<media_url_prefix>/<tenant_id>/<filename>`. `filename` stays the bare UUID
name. The `MediaFiles` mount refuses (404) a path whose tenant segment is not
the request's bound tenant in MULTI mode, so tenant A's subdomain never serves
tenant B's files. Upload, delete, variants, usage and snapshot capture/apply
use the tenant directory.

**Snapshot blobs**: `BlobStore` root becomes `<blobs_root>/<tenant_id>/`.
Otherwise `delete_unreferenced` — whose keep-set is computed from
tenant-filtered `SnapshotMedia` — would delete other tenants' blobs.
Snapshots import into the current tenant; the archive format carries no
tenant id (unchanged).

**Legacy files**: on startup, files sitting directly in `media_root` (and the
blob root) — which can only predate this change — are moved into `default/`.
Idempotent, skips anything already present, logs a count.

**Scheduler**: each tick, inside `all_tenants()`, selects the distinct
`tenant_id`s with due publish/unpublish or expired trash; then for each tenant
opens a **fresh session** under `tenant_context(id)` and runs `process_due` /
`purge_expired`. One tenant's failure is logged and does not stop the others.

**Orphan-media scan** (startup health warning): explicit `all_tenants()`,
checking `media_root/<tenant_id>/<filename>` per row.

**Dependencies**: raise `simple_module_core` and `simple_module_db` floors to
`>=0.0.35,<0.1` (ranges, per the pin policy).

## Decisions made

1. Tenant of a single-tenant host and of legacy rows is the literal
   `"default"`, matching records, so one host has one notion of it.
2. MULTI-mode admin uses the framework-resolved tenant (tenants' membership
   resolver) rather than records' `user.tenant_id`, which the framework is
   retiring (#381, after 0.0.35) in favour of memberships.
3. Startup moves legacy media/blob files into `default/` automatically rather
   than shipping an operator script.
4. `PageRevision`, `LayoutRevision`, `SnapshotMedia` get the mixin explicitly
   (issue's "explicit is safer").
5. No change to the demo host's settings (it stays single-tenant).
6. No `public_claims` signature change.
7. File layout: new `pagebuilder/tenancy.py` (+ `_tenancy_mode.py` if it would
   break the 300-line cap); new test fixtures go in a new `tests/tenant_fixture.py`
   since `conftest.py` is at the cap.

## Testing

Unit/integration (pytest, SQLite; strict mode set on the test `DatabaseState`
for the isolation tests):

- read isolation: tenant A can't fetch B's page via admin API; public viewer
  404s for B's slug on A's subdomain;
- same `(locale, slug)`, redirect `from_slug`, media filename in two tenants
  both succeed;
- rename under A creates a redirect resolvable only for A;
- layout: two tenants get two rows;
- scheduler flips due pages in two tenants, each under its own tenant;
- public request with no tenant in MULTI mode → 404 (not 500), sitemap too;
- media mount: B's file path under A's tenant → 404; legacy-file move;
- blob store GC in tenant A never deletes tenant B's blobs;
- SM024 clean for pagebuilder models; startup refuses `default_tenant != "default"`.

Migration: `alembic upgrade heads && alembic check`, downgrade/upgrade round trip.
Browser QA (`/ship`): the existing single-tenant editor, publish, media upload
and public page still work in the demo host.

## Risks

- `db.get()` answers from the identity map unfiltered; safe only because
  every session serves one tenant — the scheduler must open one per tenant.
- Core / `text()` statements are not auto-filtered; any found in pagebuilder
  need an explicit `tenant_id` predicate (audit during implementation).
- The migration recreates unique indexes on populated tables; the backfill
  must run before `NOT NULL` and before the new indexes.
- e2e tests may hard-code `/media/pagebuilder/<file>` URLs.
