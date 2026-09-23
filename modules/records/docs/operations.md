# Records — operations guide

For whoever installs, configures, deploys and keeps this module running. For
the admin screens see [user-guide.md](user-guide.md); for the wire contract see
[api-reference.md](api-reference.md).

Contents:
[Install](#install) ·
[Migrations](#migrations) ·
[Multi-tenancy operations](#multi-tenancy-operations) ·
[Settings](#settings) ·
[CLI](#the-cli) ·
[Health](#health-checks) ·
[Reindexing](#reindexing) ·
[Sidebar sync](#the-sidebar-sync) ·
[Deployment constraints](#deployment-constraints) ·
[SQLite and PostgreSQL](#sqlite-and-postgresql) ·
[Backup and restore](#backup-and-restore) ·
[Performance](#performance-headlines) ·
[Upstream issues](#upstream-framework-issues-this-module-works-around)

---

## Install

```bash
pip install simple_module_records
```

Add it to the host's dependencies. In an in-repo checkout, resolve it from the
workspace:

```toml
dependencies = ["simple_module_records"]

[tool.uv.sources.simple_module_records]
workspace = true
```

It is discovered through its entry point; no registration code is needed:

```toml
[project.entry-points.simple_module]
records = "sm_records.module:RecordsModule"
```

The module declares `ModuleMeta(name="Records", route_prefix="/api/records",
view_prefix="/admin/records", depends_on=["Settings"],
requires_framework=">=1.0,<2.0")`. It depends on the framework's **Settings**
module so that `app.state.settings.module_registry` exists by the time
`register_settings` runs. Python dependencies are declared with **ranges**
(`simple_module_core>=0.0.25,<0.1` and the same for `db`, `hosting` and
`settings`), never exact pins.

Then generate and apply the migration:

```bash
make migration msg="add records"
make migrate
```

### Optional integrations

- **`permissions`** — when the host installs the framework's `permissions`
  plugin, this module resolves permissions through it, so per-user direct
  grants work. Without it, the roles-only checker in
  `simple_module_hosting.permissions` is used and a direct `records.view` grant
  with no role attached is silently ignored (upstream
  [#337](https://github.com/antosubash/simple_module_python/issues/337)). It is
  not a hard dependency — a published module cannot require another plugin.
- **`simple_module_pagebuilder`** — when present, records contributes a
  **Records list** block to the Puck palette. Records knows about pagebuilder;
  pagebuilder does not know about records.
- **`file_storage`** (the framework's media library) — when present, a
  `media` field is edited with a picker that lists, uploads and previews files
  through that module's API, and the record list shows the first `media`
  field as a thumbnail column by default.
  Found at startup by the shape of its routes, never imported — see
  [Media library](#media-library).

---

## Migrations

**Migrations live in the host's `host/migrations/versions/`, never in the
module.** The module ships SQLModel tables; each consuming host autogenerates
its own revisions against them.

In this repo, eleven revisions belong to records:

| Revision | What it adds |
|---|---|
| `e23090832709` *(`branch_labels = ("records",)`)* | The ten core tables: `records_type`, `records_record`, `records_revision`, `records_type_revision` and the six `records_index_*` tables |
| `fccc111ff2e9` | Sort and lookup indexes |
| `a7c3e1d4b920` | Content i18n: `records_record.locale`, `translation_group`, `records_type.translatable` (hand-written — the NOT NULL columns need server defaults and a per-row backfill) |
| `26bfe5e5f063` | `records_index_reduce`, the maintained-aggregate table |
| `5e2a32dccc22` | `records_type.collection` — nullable, no backfill, because `NULL` *is* the shared table set |
| `3b4733cf5444` | The demo host's `events` collection: eight `records_c_events_*` tables |
| `fe3ea2dfe0fb` | Scopes the `(translation_group, locale)` unique index by `type_id` |
| `c4a17b9de0f2` | Descending indexes for the nullable sortable columns (a PostgreSQL planner fix) |
| `b81c5f3a27d6` | `records_type.show_in_menu` — NOT NULL with `server_default=false()` |
| `8f3d223f8605` | `<table set>_record.invalid_since` and its index — the stored "this record does not fit the schema" mark, on the global table **and on every collection's** |
| `4ecb931245dd` | Tenancy: `tenant_id` on `records_type`, `records_type_revision` and every table set's `_record` and `_revision`, backfilled `'default'`; per-tenant type-key and uuid uniques; a composite `(type_id, tenant_id)` foreign key — see below |

That is **eleven `records_*` tables** on a host with no collections, plus
**eight `records_c_<name>_*` tables** per declared collection.

`8f3d223f8605` is nullable with no server default and no backfill, so it
applies in the time one `ALTER TABLE` and one `CREATE INDEX` take per record
table and needs no downtime window. `NULL` is the honest state of every
existing row — nothing has scanned them — so an upgraded install reads exactly
as it did until the next forced schema change or **Check records** marks
anything. Downgrading drops the column and loses only which records were
marked; the derived badge is unaffected and a later check re-derives the list.

### Before upgrading past `8f3d223f8605`: `invalid` is now a reserved field key

The same change made `invalid` a fixed filter/sort column, and
`constants.RESERVED_FIELD_KEYS` derives itself from that set — so `invalid`
and `invalid_since` join `status`, `slug`, `locale` and the rest as keys a
type may not declare. **There is no migration guard for an install that
already declared one**, and the consequence is not only a refused schema save:
the stored definitions are re-validated on every read
(`services/_payload.field_defs`), so such a type answers `422` to every
request that touches it, the anonymous public API included.

Check before you upgrade — there is nothing to do if this returns no rows,
which is the usual case:

```sql
-- PostgreSQL (`records_type.fields` is a `json` column)
SELECT key FROM records_type
WHERE fields::jsonb @> '[{"key": "invalid"}]'
   OR fields::jsonb @> '[{"key": "invalid_since"}]';

-- SQLite, where the same column is text
SELECT key FROM records_type
WHERE fields LIKE '%"key": "invalid"%' OR fields LIKE '%"key":"invalid"%';
```

If it returns a type, rename the field **before** the upgrade — through the
type editor, which is still a normal remove-and-add rename (the old key's
values land under `_orphaned`, §8.2) — and re-point anything that filters or
sorts on it. Renaming afterwards is the same operation but has to be done in
SQL, because the editor cannot load a type it refuses to validate.

### Upgrading past `4ecb931245dd`: records rows gain a tenant

Every records row that exists is backfilled into tenant **`default`**, which is
the tenant a single-tenant host runs in, so nothing a reader sees changes. What
the revision does, per table set that exists in the database:

- adds `tenant_id VARCHAR(50) NOT NULL` with a temporary `DEFAULT 'default'`,
  and **drops the default again in the same revision** — a statement that
  forgets the tenant afterwards fails instead of landing in `default`;
- replaces `UNIQUE (key)` on `records_type` with `UNIQUE (tenant_id, key)`, and
  each set's `UNIQUE (uuid)` with `UNIQUE (tenant_id, uuid)`;
- adds `UNIQUE (id, tenant_id)` to `records_type` and turns each set's
  `type_id` foreign key into `(type_id, tenant_id) → records_type (id,
  tenant_id)`, under the same name, so a record can never be in a different
  tenant from its type.

**Lock profile (PostgreSQL).** The column and the default drop are catalog-only
(about a millisecond on 200,000 records, no table rewrite). The two unique
indexes block writes while they build — about half a second per 200,000
records — and the new foreign key validates every row (about 60 ms per 200,000).
Above roughly a million records, run the uniques as `CREATE UNIQUE INDEX
CONCURRENTLY` in a separate non-transactional revision and add the key `NOT
VALID` followed by `VALIDATE CONSTRAINT`, rather than applying this revision in
one maintenance window.

**SQLite** rebuilds each of the six kinds of table once (it cannot alter a
constraint in place), re-creates the three `…_desc` indexes the rebuild would
otherwise flatten to ascending, and runs `ANALYZE`. Budget it like a copy of the
records tables.

**`tenant_id` is now a reserved field key**, for the reason `invalid` became
one above, and with the same consequence for a type that already declared it.
Run the same check with `tenant_id` in place of `invalid` before upgrading.

**Downgrading is lossy.** It restores the install-wide uniques, so it is
refused outright once two tenants share a type key or a record uuid, and where
it succeeds it merges every tenant's rows with no way to separate them again.
Only a database whose rows are all `default` round-trips exactly.

### The `records@base` caveat

The first revision carries `branch_labels = ("records",)`, which makes it
nameable. **It does not make it a branch.**

```
alembic downgrade records@base    # ← rolls back EVERY revision beneath it
```

A branch label on a revision that has a `down_revision` is still a linear
revision; `<label>@base` resolves to the base of the *chain* it sits on. Because
autogenerate chains every revision off the current head, every module's first
revision sits on one linear history. Verified in this repo:
`downgrade records@base` ran 20 downgrades and emptied the database.

To remove this module's schema alone:

- downgrade to the revision **before** the records one, if records is the last
  module you added; or
- drop the eleven `records_*` tables directly, plus the eight
  `records_c_<name>_*` tables of each declared collection, and delete the
  `alembic_version` rows by hand.

Upstream:
[#333](https://github.com/antosubash/simple_module_python/issues/333).

### Collections need their own migration

A collection is declared in code, before `create_app`:

```python
# host/records_collections.py
from sm_records.collections import declare_collection

declare_collection("events")
```

```python
# host/main.py
import records_collections  # noqa: F401 - declares this host's collections

app = create_app(settings)
```

The host's `alembic/env.py` must import that module or autogenerate cannot see
the tables. In this repo `host/alembic.ini` sets
`prepend_sys_path = %(here)s` and `env.py` imports `records_collections` when it
exists. Then:

```bash
alembic -c host/alembic.ini revision --autogenerate -m "records events collection tables"
alembic -c host/alembic.ini upgrade heads
```

A collection name must match `^[a-z][a-z0-9_]*$`, be at most 22 characters (it
is a table-name prefix and the longest index built on it,
`ix_records_c_<name>_record_type_status_position`, must fit inside
PostgreSQL's 63-byte identifier limit — at 22 it lands exactly on 63) and not be one of `default`, `global`,
`records`, `type`, `index`, `reduce`. Declaring the same name twice is a no-op;
declaring one **after** the app is built is a `RuntimeError`, because those
tables are in no migration.

**A type cannot be moved between collections.** Moving records into one is
export → delete the type → recreate with `collection=` → import, **in that
order**: the importer preserves uuids verbatim, so importing before deleting
plants a duplicate and is refused.

---

## Multi-tenancy operations

Full design: [docs/plans/2026-09-23-records-multitenancy.md](../../../docs/plans/2026-09-23-records-multitenancy.md).
The short version, for whoever runs a host, not for whoever changes the module.

### Turning it on

```bash
SM_MULTI_TENANT=true
SM_TENANT_HEADER=X-Tenant-ID   # only needed if anonymous readers or API
                                # clients must choose a tenant
```

Then **restart**. The middleware stack — whether `TenantMiddleware` is in it
at all — is built once, from the environment, when `create_app` runs.
Toggling `multi_tenant` on the Settings screen instead of the environment
does not work: it edits the stored `HostSettings` row, which the stack was
already built without consulting (a framework quirk — `HostSettings` has no
`SM_` prefix registered, so the env var is the only thing that reaches the
stack build), so the process keeps running single-tenant until it restarts
with `SM_MULTI_TENANT=true` set. Records detects the mismatch by inspecting
the built stack itself rather than trusting the setting, and logs a warning
at boot when the DB row says multi-tenant but the stack has no
`TenantMiddleware` in it — the direction an admin-UI edit produces. It stays
silent about the opposite mismatch (env var on, DB row still off), which is
what every host configured only through `SM_MULTI_TENANT` looks like.

Before flipping this on a database that already has records in it, run the
pre-upgrade `tenant_id` field-key check in
[Upgrading past `4ecb931245dd`](#upgrading-past-4ecb931245dd-records-rows-gain-a-tenant)
if you have not already upgraded past that revision.

### Assigning tenants to users

The framework has no tenant concept beyond a nullable `users_user.tenant_id`,
and no UI or API to set it (`UserCreate`/`UserUpdate` carry no `tenant_id`
field, and `create_admin` takes none) — upstream
[#360](https://github.com/antosubash/simple_module_python/issues/360). Until
that lands, assign it by hand:

```sql
UPDATE users_user SET tenant_id = 'acme' WHERE email = 'someone@acme.example';
```

**Give every legacy user `tenant_id = 'default'`** — that is the tenant every
pre-migration row was backfilled into, so a user left with no tenant, the
bootstrap admin included, is refused with `403 tenant_required` on every
records admin screen rather than shown `default`'s data by accident. Records
never falls back to a guessed tenant.

**The change is invisible until the user logs out and back in.** A signed-in
user's tenant is cached in their session cookie
(`UserContext`, upstream [#362](https://github.com/antosubash/simple_module_python/issues/362)),
so a SQL `UPDATE` takes effect on their next login, not their next request.

An `admin` with no tenant of their own can be let act in whatever tenant a
request's `X-Tenant-ID` header names, instead of being refused — the
`admin_header_tenant` setting (default off; see [Settings](#settings)). A
user who *does* have a tenant always gets that one; the header never
overrides it.

### Anonymous and headless reads

The public API and the pagebuilder `RecordsList` block resolve their tenant
from the header named by `SM_TENANT_HEADER` (`X-Tenant-ID` by default); with
none, or one that does not resolve, the answer is the same `404` an unknown
type gets. **The widget's Tenant field always sends the literal header name
`X-Tenant-ID`**, not whatever `SM_TENANT_HEADER` was renamed to — using the
widget on a host that renamed the header needs `SM_TENANT_HEADER=X-Tenant-ID`
so the two agree, and remember that a cross-origin embed sending a custom
header triggers a CORS preflight the same-origin case never sees. See
[the public read API](api-reference.md#public-read-api) for the `Vary` and
`Cache-Control: private` rules this produces.

### Switching modes on a live install

**Single → multi.** Existing data stays exactly where it is, in `default`.
[Assigning tenants to users](#assigning-tenants-to-users) above decides who
sees it from that point on; nobody is refused access to `default`'s rows
until their own row gets a *different* tenant.

**Multi → single.** Only `default` is visible again: every request binds to
it, so another tenant's types and records are untouched on disk but
unreachable through any screen, endpoint or the CLI without `--tenant`. This
is never silent — `/health/ready` reports the rows left outside `default` as
an informational `tenants_outside_default` detail (§5 of
[Health checks](#health-checks) below) until they are moved back with
`--tenant`, exported and re-imported into `default`, or deleted.

### The CLI, health and the sidebar

Already covered in full where they apply to every operation, not only
tenancy:

- [`--tenant` and `records tenants`](#--tenant) — every CLI subcommand's
  tenant scoping, and the read-only tenant/type/record-count listing.
- [Health checks §5](#5-tenants-outside-default-single-tenant-hosts) —
  `tenants_outside_default`, the one detail that is informational rather than
  degrading.
- [The sidebar sync](#the-sidebar-sync) — a multi-tenant host gets the "All
  record types" hub entry only; per-type sidebar entries would leak one
  tenant's type labels to every other tenant, because the framework's menu
  registry is one process-wide list built before the request's tenant is
  known (upstream [#340](https://github.com/antosubash/simple_module_python/issues/340)).

### Upstream issues this works around

The dedicated table is at the bottom of this document —
[Upstream framework issues](#upstream-framework-issues-this-module-works-around) —
alongside the issues from the rest of the module. The tenancy-specific ones
are #355–#367.

---

## Settings

**Database-backed. No `SM_RECORDS_*` environment variable is read** — the
settings class drops pydantic-settings' env, `.env` and secrets sources
entirely, so a stray `SM_RECORDS_*` in a shell or a deploy manifest is dead.
Configure on the Settings screen, or headlessly:

```bash
python scripts/set_setting.py sm_records max_page_size 500
python scripts/set_setting.py sm_records content_locales '["en","de"]'
```

| Setting | Default | Restart? | Bounds / means |
|---|---|---|---|
| `public_route_prefix` | `/api/records/public` | **yes** | Where the anonymous read API is mounted |
| `content_locales` | `["en"]` | **yes** | The languages records may be authored in |
| `default_content_locale` | `en` | **yes** | The language a record is in when nobody says; what `?locale=` defaults to on the public API; the only language a non-translatable type accepts |
| `media_api_prefix` | `null` | **yes** | Where the `media` field picker finds the media library: `null` detects it, `""` turns the picker off, `"/api/file-storage"` names one. JSON on the Settings screen — see [Media library](#media-library) |
| `default_page_size` | `25` | no | `page_size` when the caller sends none |
| `max_page_size` | `200` | no | Largest `page_size` — clamped, not refused. At least `default_page_size` |
| `revision_limit` | `50` | no | Record revisions kept, per record. At least 1 |
| `max_filter_terms` | `20` | no | `?filter=` terms per request; each is another `EXISTS` |
| `max_sort_terms` | `5` | no | Distinct `?sort=` fields; each is another `LEFT JOIN` |
| `max_in_values` | `200` | no | Values in one `in:` list |
| `max_payload_bytes` | `262144` (256 KB) | no | One record's serialized `data` |
| `max_import_bytes` | `52428800` (50 MB) | no | One import body, refused `413` **before** parsing |
| `max_import_rows` | `20000` | no | Rows in one import, refused `413` **before** anything is written |
| `max_bulk_records` | `500` | no | Records one `POST …/records/bulk` may name, refused `413` **before** a record is touched. Does not bound `…/records/trash/empty`, which names none |
| `public_cache_seconds` | `60` | no | `max-age` on an anonymous read; `0` sends `no-store` and no `ETag` |
| `max_fields_per_type` | `100` | no | Field definitions per type |
| `max_indexed_fields_per_type` | `25` | no | Indexed field definitions per type. Must not exceed `max_fields_per_type` |
| `max_count` | `10000` | no | How far a list's `total` is counted exactly before `total_capped` |
| `max_aggregate_groups` | `1000` | no | Groups an aggregate returns before `truncated: true` |
| `preview_sync_limit` | `5000` | no | Largest type a schema preview dry-runs inside the request; above it, `202` + a job. `0` sends every preview through a job |
| `preview_job_ttl_seconds` | `600` (10 min) | no | How long a finished preview's report stays reusable by the save that follows. `0` makes every save run its own pass |
| `reindex_batch_size` | `500` | no | Records per batch in a rebuild, and the export's page size |
| `reindex_stale_after_seconds` | `900` (15 min) | no | How old a `reindex_pending` entry may get before `/health/ready` degrades |
| `menu_refresh_seconds` | `5` | no | How stale a per-type sidebar entry may get. `0` re-reads on every page request |
| `admin_header_tenant` | `false` | no | Multi-tenant hosts: let an `admin` with no tenant of their own work in the tenant their `X-Tenant-ID` header names. Off, they get `403 tenant_required` |

Everything not marked *restart* is read per request and takes effect on save.

### Why four need a restart

`public_route_prefix` because its routes are **mounted** — and exempted from
`AuthMiddleware` — from `on_startup`, which is the first point at which the
prefix is known. Module settings are hydrated at lifespan start, after
`register_routes` and `register_public_routes` have run, so reading the prefix
in either hook would read the pydantic default.

`content_locales` and `default_content_locale` are read per request, so screens
follow an edit immediately. The flag is there because an edit changes what the
install *publishes*: records already written in a dropped locale stay written,
the public API stops serving them, and they are counted **at startup only**.

`media_api_prefix` because the media library is **resolved once**, from
`on_startup`, and parked on the module's state; every screen reads that
result, not the setting.

### `public_route_prefix` is validated

It must start with `/`, must name at least one path segment, and may not be
`/api`, `/admin`, `/api/records`, `/admin/records` or a parent of any of them.
The exemption it registers disables `AuthMiddleware` for every `GET`/`HEAD`
under it, **host-wide** — so a parent path would hand the admin surface to
anonymous callers and an empty value would hand them the whole site. A value
*under* the admin API's prefix is harmless; the exemption cannot reach upwards.

A stored value that predates this rule is **logged as an error at boot and
replaced by the default** rather than failing the lifespan — the only screen
that could fix it lives in the app that would not start. Watch for:

```
records: stored public_route_prefix '/api' is invalid (…); falling back to
'/api/records/public'. Fix it on the Settings screen …
```

### Media library

A `media` field stores a media library file's **id**. Whether the admin
screens offer a picker for it depends on whether this install has a media
library, which is decided at startup:

| `media_api_prefix` | What happens at startup |
|---|---|
| `null` (default) | Detect it: a prefix under which `POST {p}/upload`, `GET {p}/files`, `GET {p}/files/{id}` and `GET {p}/files/{id}/download` are all mounted. On a stock host that is the framework's `file_storage` module, at `/api/file-storage`. |
| `"/some/path"` | Use it, without looking. If nothing matching is mounted there, a warning is logged (`does not match a media API mounted on this app`) and the picker calls it anyway — it may be a proxied API. |
| `""` | No picker, even with a media library installed: a `media` field is the id-or-URL text box. |

```bash
python scripts/set_setting.py sm_records media_api_prefix '"/api/file-storage"'
python scripts/set_setting.py sm_records media_api_prefix '""'     # off
python scripts/set_setting.py sm_records media_api_prefix null     # detect
```

The value is JSON because it has three states. It must be a path on this host
(`/…`, no scheme, no `//host`, no query): the browser calls it directly with
the admin's session cookie, and the admin screens' CSP allows `'self'`. A
stored value that fails that rule is logged as an error at boot and detection
is used instead, the same way a bad `public_route_prefix` falls back.

When detection finds **two** media APIs and none is the host's registered
`FileStorage` module, it picks neither and logs
`several media APIs are mounted (…); the media field picker is off until
media_api_prefix names one` — set the prefix to choose.

**Permissions are the media library's, not records'.** The picker lists files
with `GET {p}/files` (`file_storage.download`) and uploads with
`POST {p}/upload` (`file_storage.upload`); a user with `records.edit` but not
those sees the library's own refusal in the picker. `file_storage` maps both
to the `user` role by default. The list is every file in the library, not
only the caller's — that is how `file_storage` answers it.

**What the stock `file_storage` API cannot do**, and what the picker does
instead (to be filed upstream):

- *No search.* `GET /files` takes only `page` and `per_page`
  (`file_storage/endpoints/api.py:72`–`83`, `service.py:143`–`164`). The
  picker's search box filters the page it has loaded and says so. A media API
  whose list route declares a `q` or `search` parameter is detected and
  searched server-side instead.
- *No content-type filter and no thumbnails.* A list of files is every kind of
  file, and an image thumbnail is the full file (`GET /files/{id}/download`,
  `endpoints/api.py:121`–`155`) loaded lazily — fine for a page of 24 photos,
  wasteful for camera originals.
- *No anonymous download.* `file_storage` registers no public route
  (`module.py` overrides no `register_public_routes`) and its download
  requires `file_storage.download` (`endpoints/api.py:121`–`125`). So the
  **Records list** page block renders nothing for a `media` field, and the
  anonymous read API's `media_url_template` is always `null`.

The stable identifier is fine: `StoredFileOut.id` is a UUID primary key
(`contracts/schemas.py:17`, `models.py:28`), and a deleted file is a
soft-delete that makes `GET /files/{id}` answer `404`, which the editor shows
as **File missing** without changing the record.

### Dropping a content language

Removing a tag from `content_locales` is **not refused at save**, deliberately:
the alternative makes a typo unfixable, and records written in that language are
still perfectly good records. What happens to them:

- the public listing stops naming the language (`?locale=de` becomes a `400`
  listing the languages the site does publish);
- the public **by-uuid** read is a `404`, and a language switcher on a sibling
  stops advertising it;
- the **admin** API is untouched: those records list, read, edit, export and
  delete exactly as before;
- `/health/ready` degrades with an `orphaned_locales` detail.

To find them at any time:

```
GET /api/records/types/{key}/records?filter=locale:eq:de
```

Adding the tag back restores everything — nothing was rewritten.

---

## The CLI

Run from the repo root, so the root `.env` is what `SM_DATABASE_URL` comes from.

```bash
python -m sm_records.cli --help
```

Five subcommands: `seed`, `reindex`, `export`, `import`, and `tenants`. All of
them read the module's **stored** settings, so `reindex_batch_size` as tuned
on the Settings screen is what the CLI uses. A host whose settings tables are
not there yet falls back to the declared defaults and says so. Every one takes
`--database-url` to override `SM_DATABASE_URL` for that run.

### `--tenant`

Every records row belongs to a tenant, and a CLI process has no request to
take one from. So each subcommand takes **`--tenant T`** and works inside that
tenant only:

| Subcommand | Without `--tenant` | With `--tenant acme` |
|---|---|---|
| `export`, `import`, `seed` | `default` | `acme` |
| `reindex --type K`, `reindex --verify --type K` | looks `K` up in `default` | looks `K` up in `acme` |
| `reindex`, `reindex --verify` (no `--type`) | **every tenant**, each type in its own tenant | `acme` only |

`default` is the tenant of a single-tenant host and of every row that predates
tenancy. `T` must match `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,49}$`. Anything else is
a usage error (exit `2`), never a query. A key names a type only inside its
tenant, so `--type order --tenant acme` and `--type order` are two different
types. Output names each type as `tenant/key`.

The CLI installs the module's tenancy guard on its own connection. A code path
that reached the database with no tenant bound would fail with
`TenantUnbound`, and would not read every tenant's rows. A command that visits
several tenants opens a fresh session for each one.

### `tenants`

```bash
python -m sm_records.cli tenants
```

```
tenant   types    records    trashed
acme         3        812          4
default      5       5000          0
```

Read-only. It lists every tenant that holds at least one Record Type, with its
live and trashed record counts. Records never creates a tenant: one exists
once a user's `tenant_id`, an `X-Tenant-ID` header or `--tenant` names it and
something is written there. So this command is the only list of tenants the
module has. On a single-tenant host, a tenant other than `default` means rows
the host cannot serve. The health check reports them too
([§5 below](#5-tenants-outside-default-single-tenant-hosts)).

### `reindex`

```bash
python -m sm_records.cli reindex                            # every tenant's types with pending keys
python -m sm_records.cli reindex --tenant acme              # acme's only
python -m sm_records.cli reindex --type order               # default's order, pending or not
python -m sm_records.cli reindex --type order --tenant acme # acme's order
```

Idempotent and resumable: index rows are derived from the stored payloads, so
running it twice converges. `--type` on a type with no markers marks the whole
type first and then runs the identical operation a schema change would trigger.

```
records reindex: default/order — 9000 record(s)
records reindex: 9000 record(s) across 1 type(s)
```

With nothing pending and no `--type`: `records reindex: nothing pending`.

### `reindex --verify`

```bash
python -m sm_records.cli reindex --verify                    # every tenant
python -m sm_records.cli reindex --verify --type order --tenant acme
```

Writes nothing. Recomputes every registered reduce spec and reports each
`(type, key, group)` whose stored row disagrees with the records, as
`DRIFT tenant/type/key group …`. **Exit code `1` on drift, `0` clean**, so it
works as a deploy gate or a cron check.

"Check it" and "fix it" are deliberately separate commands: a command that
silently did both would make the drift it repaired impossible to report.

### `export`

```bash
python -m sm_records.cli export --type order --format json --out order.json
python -m sm_records.cli export --type order --format csv          # to stdout
python -m sm_records.cli export --type order --tenant acme --out acme-order.json
```

Streams a chunk at a time; a 100k-record type is exported in constant memory.
Writes `records export: default/order -> order.json (4821933 bytes)` when
`--out` is given.

### `import`

**A dry run unless `--apply`.** The default has to be the harmless one.

```bash
python -m sm_records.cli import --type order order.json            # dry run
python -m sm_records.cli import --type order order.json --apply
python -m sm_records.cli import --type order order.csv --apply \
    --mode update --match-by order_no --on-error skip --force
```

Flags: `--mode` (`upsert` | `create` | `update`), `--on-error`
(`abort` | `skip`), `--match-by` (default `uuid`), `--force`, `--apply`,
`--database-url`. Format is taken from the file extension.

Output:

```
records import: order — 9000 row(s), 0 created, 0 updated, 9000 skipped, 0 failed (dry run)
```

Exits **non-zero** with the report printed when an `abort` run is refused.

An import always writes into `--tenant` (default `default`). A JSON export
names the tenant it came from (`"tenant": "acme"`), but only as information:
the importer never reads it. So exporting with `--tenant acme` and
importing with `--tenant globex` copies acme's records of a type into
globex's type of the same key. The uuids are kept. That is legal because a
uuid is unique per tenant. The target type has to exist in the target tenant
already: `POST /types/import` or the type editor, as the user in that tenant.

This is the one place in the module that commits a session of its own — and only
after a run that was asked to apply and came back without a refusal. It calls
the same service code the HTTP endpoints do, so a file imported from the command
line goes through the same validation, relation checks, revisions and index
writes as one uploaded through the browser.

### `seed`

Demo data: five Record Types (`company`, `contact`, `product`, `store`, `order`,
with relations between them) written through the real services, so a seeded
install has the same index rows, revisions and relation checks a hand-built one
would.

```bash
python -m sm_records.cli seed                          # 5000 records, seed 42
python -m sm_records.cli seed --records 2000 --seed 7
python -m sm_records.cli seed --reset                  # purge the demo types first
python -m sm_records.cli seed --tenant acme --reset    # acme's demo types only
python -m sm_records.cli seed --database-url sqlite+aiosqlite:///path/to.db
```

`--records` is the *total* across all types (roughly 5% company / 25% contact /
15% product / 45% order / 10% store, minimum one each). It is deterministic for
a given `--seed`; re-running without `--reset` tops the dataset up. `--reset`
hard-deletes the demo types and everything in them, trash included, **in
`--tenant` only**. Another tenant's `company` is a different type that the
reset never sees.

On a host that declares the `events` collection the seeder adds a sixth type,
`event`, in that collection, with a relation pointing at the **global** `store`
type — so the dataset exercises a relation across a collection boundary. On a
host with no collection the type is skipped entirely.

On an install with more than one content locale the seeder marks `company`
translatable and gives roughly a tenth of the companies a sibling in the second
locale.

Every record goes through `create_record`, so this is the slow path: **10,000
records took 1 minute 46 seconds (94 records/s)** on SQLite. The run finishes
with one `ANALYZE` pass over the module's own tables — a bulk load is exactly
the state SQLite has no planner statistics for.

For an in-process caller, call
`sm_records.seed.seed_database(db_state, settings, records=…, seed=…,
reset=…)` directly instead of shelling out.

---

## Health checks

The module registers one health check, `records.reindex`. Four separate faults
degrade `/health/ready` through it, and they are reported together rather than
one hiding another. A fifth detail, on single-tenant hosts only, is
informational and never degrades the check on its own (§5).

The check reads **every tenant**, whatever tenant the `/health/ready` request
itself was bound to. Each row it names carries its tenant: `tenant/key` for a
type and `tenant/locale` for a language, and the invalid count is broken down
per tenant.

### 1. A stale reindex

```
reindex pending for longer than 900s: default/order (placed_at, total) — run `python -m sm_records.cli reindex`
```

A `reindex_pending` entry older than `reindex_stale_after_seconds`. Usually a
background rebuild whose worker restarted. **Clear it** with
`python -m sm_records.cli reindex`, or with `POST
/api/records/types/{key}/reindex`, or with **Reindex now** in the type editor.

If a `unique` field is among the stale keys the detail adds:

```
; a unique field is among them, so writes to this type are refused until the rebuild completes
```

That is not a warning about slowness. The uniqueness check is a query over the
index, and it refuses a pending field — so **every write to the type is a 409**
until the rebuild finishes. Treat it as an outage of that type.

### 2. Reduce drift

```
reduce_drift: …
```

A maintained aggregate that the last verify found disagreeing with the records.
This is **in-process state**: it reflects verifies run by *this* worker. A CLI
`reindex --verify` runs in another process and reports on its own stdout
instead. **Clear it** with a clean verify or a rebuild
(`python -m sm_records.cli reindex --type KEY`).

### 3. Invalid records

```
invalid_records: 12 (acme: 3, default: 9) — record(s) marked as not satisfying
their type's schema, from a forced schema change; each one's next save clears
the mark (filter=invalid:eq:true)
```

Counted from `invalid_since` on every check, which is affordable because both
backends answer `IS NOT NULL` out of that column's own index by reading only
the entries that have a value — the cost is the number of marked records, not
the number of records.

**It is not an error.** Forcing a restrictive change is a decision somebody
made deliberately, and the records are still served and still editable. What
the line is against is forgetting: an install that has carried the same twelve
marked records for a month is one where nobody wrote down the worklist.
**Clear it** by working through
`/admin/records/<type>?filter=invalid:eq:true` — each record's next successful
save clears its own mark — or, if the schema was the mistake, by relaxing the
rule and running **Check records**, which clears the mark on every record that
now fits.

### 4. Orphaned locales

```
orphaned_locales: {default/de: 12} — records in a language this install no
longer publishes; they are hidden from the public API and still editable in the
admin (filter=locale:eq:<tag>)
```

**Counted once, at startup, and only there.** The framework's settings registry
offers no post-hydration hook to recompute it from, so an operator who drops a
locale sees the count at the next restart — which the setting needs anyway.
**Clear it** by translating those records into a language you do publish, by
deleting them, or by putting the tag back.

### 5. Tenants outside `default` (single-tenant hosts)

```
tenants_outside_default: {acme: 3 type(s), 816 record(s)} — this host is
single-tenant and serves only 'default'; these rows are untouched but
unreachable (`python -m sm_records.cli tenants`)
```

**Informational: it never degrades the check.** An operator may keep another
tenant's rows on a single-tenant host on purpose, and a check that stayed
DEGRADED for that would teach everyone to ignore it. The detail rides on
whatever status the other findings give — on a HEALTHY result when it is the
only one (`/health/ready` shows a check's `detail` whatever its status).

Reported only on a host whose middleware stack has no `TenantMiddleware`
(`SM_MULTI_TENANT` unset or false). Such a host binds every request to
`default`, so rows in any other tenant are invisible to every screen and
endpoint. They get there in two ways: a CLI run with `--tenant`, or a host
switched from multi-tenant back to single-tenant. Nothing is deleted. **Clear
it** by switching the host to multi-tenant, by exporting those types with
`--tenant` and importing them into `default`, or by deleting them with the
CLI in that tenant. Each entry gives the tenant's types, then its records
including the trash. It costs nothing on a host with no such rows: the tenants come from
the type rows the stale check already reads.

The check answers HEALTHY while the module has no database handle — during boot
there is nothing to be stale yet, and a health check that fails because it ran
early is worse than no check at all.

---

## Reindexing

`records_type.reindex_pending` is a mapping of `{field_key: ISO-8601
enqueued-at}`. The reserved key `*` means "rebuild the whole type" and is
enqueued by a `display_field` change, because every record's `display_title` is
denormalized from it.

While a key is listed, **filters and sorts on that field are refused with a
`409`** (`reason: "reindexing"`) rather than answered from rows that are half
moved. That is deliberate: refusing loudly for a few seconds beats partial
results returned without comment.

An index-affecting schema change enqueues the rebuild and it runs **after the
response**, through the module's own deferred-job middleware — not FastAPI's
`BackgroundTasks`, which runs inside the scheduling request's dependency
teardown and therefore inside its still-open transaction (on SQLite that is a
deadlock the driver breaks with `database is locked`).

The runner commits per batch, which is what bounds SQLite's write lock, and
clears `reindex_pending` last, so a crash anywhere leaves the markers set and a
re-run converges.

A rebuild moves roughly **3,000–4,500 records/second** on SQLite at
`reindex_batch_size` 500; bigger batches are better.

### Maintained aggregates

A **reduce provider** keeps a running aggregate of a whole type, updated by
delta on every write. It is opt-in, registered in code, and it exists for one
problem only: a `GROUP BY` over a type so large that the live `/aggregate` has
become too slow.

Three operational facts:

- **Every worker must run the same registrations.** The registry is
  process-global; a worker that skipped one writes no deltas, and what it writes
  goes missing from the stored aggregate until a rebuild.
- **Registering or changing a spec marks nothing.** A provider is code you
  deploy, not a schema edit this module can see. Run
  `python -m sm_records.cli reindex --type KEY` after deploying one.
- **Drift is detectable, not impossible.** `reindex --verify` is the gate.

The same three apply to **index providers** (virtual fields): run a reindex
after deploying a changed one, and make sure every worker registers it.

---

## The sidebar sync

The framework's `MenuRegistry` is filled once per process, at app construction.
Record Types are created long after that, so a type with `show_in_menu` has its
entry added by this module's own sync.

- The worker that served the type write re-reads on its **next** request that
  renders a sidebar.
- Every other worker re-reads within `menu_refresh_seconds` (5 by default).
- `0` re-reads on every page request — one query per page, for an install that
  would rather never show a stale sidebar.

**Multi-tenant hosts get no per-type entries**, only "All record types". The
registry is one list per process, and the sync runs before the request's
tenant is known. Per-type entries would show each tenant's type labels to
every other tenant, linking to keys that resolve differently per viewer. The
hub page lists the viewer's own tenant's types, so nothing becomes
unreachable. On a single-tenant host the sync reads `default`'s types, as
before.

Requests under `/api/`, `/static` and `/health` never trigger a re-read: none of
them renders a sidebar.

A failed read (a boot before the migration, a transient error) is logged and
otherwise ignored; the previously synced items stay in place. The clock is reset
too, so a database that is down costs one query per window rather than one per
request.

```
records: could not read the sidebar types; keeping the previous entries
```

**This is the only place the module reaches into framework internals** — the
registry has no remove and no dynamic provider hook. Upstream:
[#340](https://github.com/antosubash/simple_module_python/issues/340).

---

## Deployment constraints

Three things are single-process by design. State them as constraints, because
they decide how you deploy.

### 1. Schema-preview jobs live in memory

`POST /types/{key}/schema/preview` on a type over `preview_sync_limit` answers
`202` with a job id and runs the scan in **this worker's** memory. A poll that
lands on another worker answers `404`; the client falls back to previewing
again, which writes nothing.

The registry is bounded by count, pruned by age and gone on restart. That is
correct rather than a limitation: a report is a claim about records as they were
when it was taken, and persisting one invites a caller to apply it later against
a database it no longer describes.

**Consequence:** behind a load balancer with no session affinity, a preview of a
large type may never converge through polling. Either set `preview_sync_limit`
high enough that previews stay synchronous (and accept the long request), or set
it to `0` and accept that the UI will retry.

### 2. A deferred reindex runs in the worker that received the request

An index-affecting schema change schedules its rebuild on the worker that served
the `PUT`. If that worker restarts before the rebuild finishes, the markers stay
set, the affected fields keep refusing filters, and `/health/ready` degrades
after `reindex_stale_after_seconds`. The fix is always the same:
`python -m sm_records.cli reindex`.

A deferred job also runs **in the tenant of the request that queued it**, both
the rebuild and the event publication. The drain runs after the request's own
tenant binding has been reset, so the module captures the tenant when the job
is queued and binds it again around the job. The CLI without `--type` finishes
every tenant's pending rebuilds.

**Consequence:** make sure something watches `/health/ready`, and make sure an
operator can run the CLI against production.

### 3. The provider registries are process-global

Index providers and reduce specs are registered in Python at import time or from
a module's `on_startup`. Every worker must run the same registrations, or
workers disagree about what is indexed.

### And one that is not about processes

**`unique` is enforced by the application, not by a database constraint.** The
index tables are shared across every field of a kind, so a partial unique index
naming a runtime-chosen field key is not possible. A `unique` field is checked
with a `SELECT … LIMIT 1` inside the write's transaction, and writes to the type
are **serialized** to close the check-then-act race: a row lock on the type on
PostgreSQL, and a write against the type row (which takes SQLite's `RESERVED`
lock) on SQLite.

Read that as "unique enforced at the cost of serializing writes on that type",
not as a database-level guarantee. A type with a `unique` field has a write
throughput ceiling.

---

## SQLite and PostgreSQL

Both are supported and share the same table layout. SQLite is the local-dev
default (`host/app.db`).

Differences that matter:

- **`number` precision.** The index column is `Numeric(19, 5)`. That contract is
  exact on PostgreSQL. SQLite has no native decimal type, so SQLAlchemy stores
  `Numeric` there as a floating-point `REAL` — approximate. Callers wanting more
  precision want a `text` or `json` field.
- **Write serialization.** The per-type lock is `SELECT … FOR UPDATE` on
  PostgreSQL and a write against the type row on SQLite, because `FOR UPDATE`
  locks nothing there.
- **Planner statistics.** SQLite with no statistics plans an index filter badly
  enough to be quadratic; the seeder runs `ANALYZE` over the module's tables for
  exactly this reason, and so does the reindex. Run `ANALYZE` after any bulk
  load into a SQLite database.
- **Sort indexes.** Revision `c4a17b9de0f2` exists because a *descending* sort on
  a nullable column (`ORDER BY col DESC NULLS LAST`) is neither direction of an
  ascending btree on PostgreSQL, so the planner ignored the index and sorted the
  type.
- **Identifier length.** PostgreSQL truncates identifiers at 63 bytes, which is
  why a collection name is capped at 22 characters —
  `ix_records_c_<name>_record_type_status_position` is the longest identifier a
  table set builds, and 22 puts it exactly on the limit. Foreign-key names are
  longer still and are not what the cap protects: the naming convention spells
  both table names into one identifier, so every collection's index-to-document
  key is past 63 and SQLAlchemy hash-truncates it
  (`fk_records_c_events_index_date_record_id_records_c_even_2956`). A
  hand-written `DROP CONSTRAINT` has to use that spelling, not the logical one.
- **Index key length.** The text index column is 512 characters — 2,048 bytes at
  four-byte UTF-8, under PostgreSQL's 2,704-byte btree ceiling. Redo that
  arithmetic before raising it.

### Running the test suites against PostgreSQL

Every suite in this repo defaults to in-memory SQLite and takes one opt-in
variable instead:

```bash
SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/smpy_test \
  uv run pytest -q
```

One name for all of them — `records`, `pagebuilder` and `news` each reach the
repo-root `tests/pg_support.py` through a small shim in their own `tests/`
directory, which creates the schema once per process and empties it with
`TRUNCATE ... RESTART IDENTITY CASCADE` between tests. `RECORDS_TEST_URL` is
still read, as an alias, when `SM_TEST_DATABASE_URL` is unset. Nothing is
selected unless one of them is set, so a plain `pytest` is unchanged.

The PostgreSQL verification run, and every behavior that differs from SQLite, is
in [postgres-2026-09-21.md](postgres-2026-09-21.md). The PostgreSQL
measurements are in [performance.md](performance.md). CI now runs this
verification on every PR: the `postgres` job in `.github/workflows/ci.yml`
round-trips the migrations against a `postgres:16` service, runs this
module's unit suite against it (`RECORDS_TEST_URL`), and does a short perf
smoke — the SQLite-only suites elsewhere in CI are unaffected.

---

## Backup and restore

The module's own tables are ordinary tables; a database-level backup covers
them. What the export/import pair gives you on top is a **portable, per-type,
reviewable** copy.

### Per-type backup

```bash
python -m sm_records.cli export --type order --format json --out order.json
python -m sm_records.cli export --type order --format csv  --out order.csv
```

Back up the **definition** separately — `GET /api/records/types/{key}/export`,
or the `"type"` header the JSON export already carries.

### Restore

```bash
# 1. the definition, if the type does not exist on the target
curl -s -b cookies.txt -X POST http://localhost:8000/api/records/types/import \
  -H 'Content-Type: application/json' --data @order-type.json

# 2. the records — dry run first
python -m sm_records.cli import --type order order.json
python -m sm_records.cli import --type order order.json --apply
```

Facts worth relying on:

- **A round trip is idempotent.** `uuid` travels, so re-importing an export
  converges; rows the record already agrees with are **skipped**, not written,
  so versions do not move.
- **An import writes through the same services a single save does**, so
  revisions, index rows, `unique` and slug claims and the per-type lock all
  behave exactly as they do for a hand edit.
- **`on_error=abort` is all-or-nothing** — the request's transaction is rolled
  back.
- **A trash export cannot be re-imported.** Restore or purge the records first;
  a row matching a trashed record is refused.
- **`version` does not travel**, so updating an existing record from an export
  needs `--force` (last write wins).
- **uuids are unique across every table set of a tenant**, so a global type's
  export cannot be imported into a collection type that already holds those
  uuids — which is why moving a type into a collection is purge-then-import in
  that order. Another tenant's copy of a uuid does not count: an export from one
  tenant imports into another with its uuids intact.

---

## Performance headlines

The full picture, with methodology and before/after tables, is in
[performance.md](performance.md); the original 100k-record study is
[perf-study-2026-09-19.md](perf-study-2026-09-19.md).

Measured on SQLite, 9,000 `order` records, p50 over 20 repetitions:

| Operation | Cost |
|---|---|
| `GET /api/records/types/order/records` page 1 | **14.0 ms** |
| the same with `?total=false` | **8.5 ms** |
| `GET /admin/records/order` (Inertia, 8 statements) | **37.6 ms** |
| live aggregate, `group_by=ship_state` | **27.8 ms**, 2 statements on any type |
| the same fold read from a reduce index | **6.8 ms**, 3 statements |
| rebuilding a reduce fold over 9,000 records | 398 ms — **22,612 rec/s** |
| rebuilding the index, `reindex_batch_size` 500 | **~4,400 rec/s** |
| seeding through the real services | **~94 rec/s** |
| importing an unchanged export (every row skipped) | **~917 rows/s** |
| exporting 9,000 records as JSON | ~1,380 ms |

Things to watch:

- **A page costs about 2–3 ms more than it used to**, constant per request, for
  the bounded count and the cursor encoding. `?total=false` gets most of it
  back — send it from anything that pages with `?after=`.
- **`contains` scans; `starts_with` seeks.** The relation picker asks in that
  order for a reason.
- **`?locale=` is free** — locale is a column on the record row, not a join.
- **An install that uses none of the Phase 5 features pays for none of them**: no
  reduce spec registered means no statement issued, one content locale means the
  sibling query is never run, no collection declared means the same statements as
  before collections existed.

Run the suite yourself:

```bash
cd modules/records && RECORDS_PERF_N=20000 ../../.venv/bin/python -m pytest -q -s -m perf tests/perf -p no:cacheprovider
```

`-s` is load-bearing (the results table is printed from a session fixture).
`RECORDS_PERF_DB` points it at a SQLite file seeded elsewhere and
`RECORDS_PERF_URL` at another backend.

---

## Upstream framework issues this module works around

All are open against
[antosubash/simple_module_python](https://github.com/antosubash/simple_module_python).

| Issue | What it is | What records does about it |
|---|---|---|
| [#332](https://github.com/antosubash/simple_module_python/issues/332) | Soft-delete and tenant filters are skipped for selects that name no mapper (`select(func.count())`) — a [comment](https://github.com/antosubash/simple_module_python/issues/332#issuecomment-5794906795) measures the same gap's breadth: join targets, `exists()`/`in_()` subqueries, `update()`/`delete()`, and an already-loaded `session.get()` | Every count selects `func.count(Record.id)` over the mapped entity, never `count()` over a bare `select_from`; every other shape in the comment gets an explicit `tenant_id == bound_tenant()` predicate (design §E), checked by a statement census that runs over the whole suite on PostgreSQL |
| [#333](https://github.com/antosubash/simple_module_python/issues/333) | `alembic downgrade <label>@base` walks the whole revision chain | The README and [Migrations](#the-recordsbase-caveat) above say what the label actually buys, and how to drop the tables instead |
| [#334](https://github.com/antosubash/simple_module_python/issues/334) | No runtime permission source for resources defined after boot | Per-type access is `RecordType.allowed_roles`, not a framework permission — which is why it is invisible in the role editor |
| [#335](https://github.com/antosubash/simple_module_python/issues/335) | No supported way to hard-delete a `SoftDeleteMixin` row | A purge goes through the module's own `hard_delete_record`, which issues core DML rather than `session.delete()` |
| [#336](https://github.com/antosubash/simple_module_python/issues/336) | `get_db` auto-commit ignores core DML, so a request whose only write is `session.execute(update(...))` is rolled back | `services._common.mark_written` sets the flag the framework's `after_flush` listener would have set |
| [#337](https://github.com/antosubash/simple_module_python/issues/337) | Two `RequiresPermission` classes; the hosting one silently ignores per-user grants | `deps.py` prefers `permissions.deps.RequiresPermission` when the `permissions` plugin is installed, and falls back to the hosting one when it is not |
| [#338](https://github.com/antosubash/simple_module_python/issues/338) | `AdminLayout` mounts no `<Toaster>`, so `toast.*()` is swallowed on every admin page | The module ships its own `RecordsToaster` and mounts it on its screens |
| [#339](https://github.com/antosubash/simple_module_python/issues/339) | The SQLite engine is left at driver defaults: rollback journal, implicit 5 s busy timeout, foreign keys **off** — a [comment](https://github.com/antosubash/simple_module_python/issues/339#issuecomment-5795747765) adds that the tenancy migration's composite `(type_id, tenant_id)` FK is therefore unenforced on a SQLite host | `on_delete` is enforced in the application rather than by FK cascades, and the reindex runner retries a short bounded backoff on `database is locked`; the composite type FK is proven only by tests that turn `PRAGMA foreign_keys=ON` themselves — a SQLite production host gets no such guarantee |
| [#340](https://github.com/antosubash/simple_module_python/issues/340) | `MenuRegistry` has no way to remove items or contribute them dynamically — a [comment](https://github.com/antosubash/simple_module_python/issues/340#issuecomment-5794907667) proposes a per-request `register_menu_provider(request -> items)` for a per-tenant sidebar | `sm_records.menu.sync_type_menu` splices the registry's item list by object identity — one function, the module's only reach into framework internals; on a multi-tenant host it syncs no per-type items at all rather than leak one tenant's labels to another ([The sidebar sync](#the-sidebar-sync)) |
| [#341](https://github.com/antosubash/simple_module_python/issues/341) | `AdminLayout`/`SidebarLayout` have no skip link, and five chrome tab stops precede the first page control | Not worked around; the module's own per-type sidebar entries add to the count. Fixing it belongs upstream |
| [#342](https://github.com/antosubash/simple_module_python/issues/342) | Migrations autogenerated on SQLite are not portable to Postgres (boolean defaults as `text('0')`, expression indexes invisible, enum types left behind on downgrade), and every check reports them clean | This host's revisions were corrected by hand (`ed06f4584f6b`, `4cf1b4c9f8f9`, `b98d8185ecef`, `d2b7a1c4e905`); see [postgres-2026-09-21.md](postgres-2026-09-21.md) § 2 |
| [#343](https://github.com/antosubash/simple_module_python/issues/343) | `simple_module_test` fixtures hard-code in-memory SQLite, so a module suite cannot run on Postgres | The repo-root `tests/pg_support.py` and `SM_TEST_DATABASE_URL` do it for `records`, `pagebuilder` and `news`; see [postgres-2026-09-21.md](postgres-2026-09-21.md) § 3 and § 13 |

### Filed for `MultiTenantMixin`/`TenantMiddleware` (#355–#367)

Found while making this module multi-tenant; design
[2026-09-23-records-multitenancy.md](../../../docs/plans/2026-09-23-records-multitenancy.md)
§L has the full gap table (L1–L17) and why each one cannot be fixed inside
this module.

| Issue | What it is | What records does about it |
|---|---|---|
| [#355](https://github.com/antosubash/simple_module_python/issues/355) | `MultiTenantMixin`: reads with no tenant bound return every tenant's rows | `install_guard` raises `TenantUnbound` on any unbound ORM statement over an owned mapper, instead of trusting a tenant happens to be set (`tenancy.py`, design §A.4) |
| [#356](https://github.com/antosubash/simple_module_python/issues/356) | `MultiTenantMixin`: unbound flush skips the tenant-change check, letting a row move silently | The same guard's `before_flush` refuses an unbound create, update or delete of an owned row |
| [#357](https://github.com/antosubash/simple_module_python/issues/357) | `MultiTenantMixin`: bulk `insert()` is not stamped with `tenant_id` | Records never bulk-inserts an owned (mixin) table — only the derived index/reduce tables, which carry no `tenant_id` column at all (design §B) |
| [#358](https://github.com/antosubash/simple_module_python/issues/358) | `TenantMiddleware`: the header chooses the tenant for *any* authenticated user with no tenant of their own | `resolve_admin` ignores the header for a signed-in user and answers `403 tenant_required`, unless the operator turned the module's own `admin_header_tenant` setting on for `admin` users |
| [#359](https://github.com/antosubash/simple_module_python/issues/359) | No default-tenant setting or `tenant_scope` helper for `MultiTenantMixin` | `sm_records.tenancy.DEFAULT_TENANT` (a constant, not a setting — see design §A.3) and `tenant_scope()` (always resets, refuses re-binding to a different tenant) are the module's own |
| [#360](https://github.com/antosubash/simple_module_python/issues/360) | `users`: no tenant management — `UserCreate`/`UserUpdate` and `create_admin` have no `tenant_id` | Not worked around; operators assign `users_user.tenant_id` by SQL — see [Assigning tenants to users](#assigning-tenants-to-users) |
| [#361](https://github.com/antosubash/simple_module_python/issues/361) | `file_storage`: `StoredFile` is not tenant-scoped | Not worked around; a `media` field's stored file id from one tenant is silently accepted by another. Records does not own `file_storage` |
| [#362](https://github.com/antosubash/simple_module_python/issues/362) | `users`: a tenant change is invisible until re-login, because `UserContext` is cached in the session | Documented as an operator step — see [Assigning tenants to users](#assigning-tenants-to-users) |
| [#363](https://github.com/antosubash/simple_module_python/issues/363) | `TenantMiddleware`: anonymous tenant resolution is header-only, with no pluggable resolvers (path, host) | Matches how `bind_public` already resolves; documented as a limitation for hosts that would rather not use a header |
| [#364](https://github.com/antosubash/simple_module_python/issues/364) | `hosting`: module middleware runs outside `Tenant`, so deferred work (and this module's own menu sync) loses the tenant | `deferred.defer()` captures `bound_tenant()` when a job is queued and re-binds it around the drain, which runs after the request's own binding has been reset (design §A.5) |
| [#365](https://github.com/antosubash/simple_module_python/issues/365) | `simple_module_db`: no `tenant_scope` helper, so `current_tenant_id` hygiene (always reset, never a bare `set()`) is every caller's problem | `tenancy.tenant_scope()` is the module's own, and is the only place `sm_records` sets the contextvar |
| [#366](https://github.com/antosubash/simple_module_python/issues/366) | `TenantMiddleware` binds the header value unvalidated — an over-long or malformed value becomes an unhandled `500` on write | `bind_public`/`resolve_admin` validate against `TENANT_RE` (`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,49}$`) and treat a value that fails it as *no tenant*, never as a query |
| [#367](https://github.com/antosubash/simple_module_python/issues/367) — "upstream (tenant source)" in earlier phase notes | `TenantMiddleware` does not say whether a request's tenant came from the signed-in user or the header, so a cacheable anonymous read cannot set `Vary` correctly | The public API marks a signed-in reader's answer `Cache-Control: private` (their tenant came from their account, which no header names) and reserves `Vary: <tenant header>` for header-resolved answers, re-deriving the distinction `request.state.user` already gives it |
