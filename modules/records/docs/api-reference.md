# Records — API reference

Two HTTP surfaces:

- the **admin API** at `/api/records`, which needs a session and one of the
  three `records.*` permissions;
- the **public read API** at the `public_route_prefix` setting
  (`/api/records/public` by default), which needs no session and serves only
  the published records of types marked `is_public`.

The admin views under `/admin/records` render the same data through Inertia and
parse the same query grammar, so a deep link into the UI and the equivalent API
call return the same set. Writes always go through the JSON API.

Contents:
[Conventions](#conventions) ·
[Query grammar](#query-grammar) ·
[Types](#type-endpoints) ·
[Records](#record-endpoints) ·
[Relations](#relation-endpoints) ·
[Revisions](#revision-endpoints) ·
[Translations](#translation-endpoints) ·
[Aggregate](#aggregate) ·
[Schema changes](#schema-change-endpoints) ·
[Domain events](#domain-events) ·
[Import and export](#import-and-export-formats) ·
[Public read API](#public-read-api) ·
[Errors](#error-table) ·
[Limits](#limits-that-bound-a-request)

---

## Conventions

### Permissions

| Permission | Covers |
|---|---|
| `records.view` | Reads: type list, type read, record list and read, referrers, revisions, aggregate, export |
| `records.edit` | Record writes, trash listing, restore, purge, record import |
| `records.manage_types` | Type create/update/delete, schema preview, type revisions and rollback, reindex, type import |

A type's `allowed_roles`, when non-empty, narrows `records.view` and
`records.edit` on **that type's records** with no admin bypass. A caller
outside the list gets `403` on every record surface of the type, and the type is
omitted from `GET /api/records/types` altogether. `records.manage_types` holders
keep access to the type's *definition* (`GET /types/{key}`, `…/revisions`,
`…/export`) regardless.

### Error body

Every deliberate refusal is JSON. The base shape is:

```json
{"detail": "human-readable message"}
```

Four refusals carry more; see the [error table](#error-table).

### Optimistic concurrency

Every update carries `expected_version`. A mismatch is `409` with the current
row under `current`, so a client can diff rather than merely retry.

### Identifiers

A record is addressed by its `uuid`: 32 lowercase hex characters, no dashes,
unique across every table set on the install.

---

## Query grammar

### `?filter=` — repeatable, ANDed

One term is `field:op:value`, split on the **first two** colons so a value may
contain its own (a URL, an ISO timestamp).

```
?filter=order_status:eq:paid&filter=total:gte:100
```

`field` is either an **indexed declared field**, a **fixed column**, or a
**virtual field** an index provider registers. A declared but unindexed field is
refused; so is an unknown one.

| Operator | Meaning |
|---|---|
| `eq` | Equals. On a multi-valued field: holds this value |
| `ne` | Does not equal. On a multi-valued field: holds no such value. Also matches a NULL fixed column |
| `in` | `in:a,b,c` — equals any of them |
| `contains` | Case-insensitive substring. Scans |
| `starts_with` | Prefix. Case-sensitive in code-point order on every database; seeks the index on SQLite and `C`-collated Postgres, filters one field's rows under a linguistic collation |
| `gt` `gte` `lt` `lte` | Ordered comparison |
| `is_null` | `is_null:true` — the record has no value for the field; `is_null:false` — it has one |

Which operators are valid depends on the field's **index kind**:

| Field types | Index kind | `eq` `ne` `in` | `contains` `starts_with` | `gt` `gte` `lt` `lte` | `is_null` |
|---|---|---|---|---|---|
| `text`, `select`, `multiselect`, `email`, `url` | text | yes | yes | **no** | yes |
| `number`, `integer` | number | yes | no | yes | yes |
| `boolean` | bool | `eq` and `ne` only (no `in`) | no | no | yes |
| `date` | date | yes | no | yes | yes |
| `datetime` | datetime | yes | no | yes | yes |
| `relation` | ref | yes | no | no | yes |
| `longtext`, `json`, `media` | *not indexable* | — | — | — | — |

Text is deliberately not ordered-comparable: the indexed column holds only the
first 512 characters, so `>` over it would answer with a prefix. An `eq` on a
longer value is re-checked against the untruncated column, and `contains`
searches both.

**Fixed columns** — every record has these whatever its type declares, and they
need no `indexed: true`:

| Column | Operators |
|---|---|
| `status` (`draft` / `published`) | `eq` `ne` `in` `is_null` |
| `display_title` | `eq` `ne` `in` `contains` `starts_with` `is_null` |
| `slug` | `eq` `ne` `in` `contains` `starts_with` `is_null` |
| `locale` | `eq` `ne` `in` `is_null` — matched whole, never by prefix |
| `position` | `eq` `ne` `in` `gt` `gte` `lt` `lte` `is_null` |
| `published_at`, `created_at`, `updated_at` | `eq` `ne` `in` `gt` `gte` `lt` `lte` `is_null` |
| `invalid` | `eq` `ne` `is_null` — a **boolean** over the `invalid_since` column |

`invalid` is the one fixed column whose name is not its column's. The row
stores `invalid_since`, a nullable timestamp, and the filter is the boolean
view of it: `invalid:eq:true` is `invalid_since IS NOT NULL`, and
`invalid:eq:false`, `invalid:ne:true` and `invalid:is_null:true` all select
the records with no mark. `contains`, `starts_with` and the ordered operators
are refused by name — they would compare against a timestamp the name does not
mention. **`?sort=invalid` orders by that timestamp**, under `NULLS LAST`: the
marked records first, oldest mark first, everything else behind them.

Fixed-column names are reserved as field keys, so a type cannot declare one and
have it answered from the wrong place. That covers `invalid` and
`invalid_since` alike.

### `?sort=` — repeatable, a leading `-` is descending

```
?sort=-placed_at&sort=order_no
```

Repeats of the same field are deduplicated (the first occurrence decides the
direction), then the count of distinct fields is capped. Fixed columns and
indexed declared fields alike may be sorted on. The record-list *screen* writes
only one sort term; the grammar accepts several.

The admin record list defaults to `position` ascending, then `updated_at`
descending, when the caller sends no `?sort=`.

### Paging

| Parameter | Default | Meaning |
|---|---|---|
| `page` | `1` | Offset paging. Maximum `1000000` — beyond that is a `422` from parameter validation |
| `page_size` | `default_page_size` (25) | Clamped to `max_page_size` (200) rather than refused |
| `after` | — | Keyset cursor. Returns the page after the row a previous page's `next_cursor` names, with no `OFFSET` |
| `total` | `true` | `total=false` skips the count statement entirely; `total` comes back `null` |

`page` and `after` together is a `400`: they are two ways of asking for a page
and the server will not guess.

`total` is exact up to `max_count` (10,000). Above it, `total` is `max_count`
and `total_capped` is `true`.

**Walking a large type:**

```bash
url='/api/records/types/order/records?page_size=200&sort=-placed_at&total=false'
while [ -n "$url" ]; do
  page=$(curl -s -b cookies.txt "http://localhost:8000$url")
  echo "$page" | jq -r '.items[].uuid'
  cursor=$(echo "$page" | jq -r '.next_cursor // empty')
  [ -n "$cursor" ] && url="/api/records/types/order/records?page_size=200&sort=-placed_at&total=false&after=$cursor" || url=''
done
```

A full final page still returns a `next_cursor`; the request after it comes back
empty with `next_cursor: null`. "Fewer rows than asked for" is the only
end-of-data signal that survives a capped `total`.

The cursor is opaque base64 (the row's sort values plus its id) but not secret.
It carries a digest of the sort it was produced under — the type, the ordered
`(field, direction)` list, whether the listing was the trash, the index kind
behind each sort field, and on the public API the `?locale=` it was narrowed to.
Replaying it under a different sort is a `400`, as is a cursor that does not
decode.

**In the admin list screen.** `GET /admin/records/{key}` (the Inertia view)
takes `after` too, beside `page`, `page_size`, `filter`, `sort` and `trashed`,
and it is the same cursor: the view's `records` prop carries `next_cursor` on
every page, and a `next_cursor` from this endpoint resumes the view under the
same explicit `sort`. The view's default order (`position`, then `updated_at`
descending) is not this endpoint's, so a cursor minted with no `?sort=` on one
is refused by the other. A page reached by `after` comes back with
`page: null` — it is past the numbered pages and has no number — and still
counts `total` up to `max_count`.

The view never answers with an error status: a page navigation that failed
would be an error modal over a screen that can say what went wrong. Each
paging `400` above is instead the list's notice, via `errors.filter` on a
`200` with no rows:

| Request | `errors.filter` |
|---|---|
| A cursor that does not decode, or was produced under another sort, trash view or field kind | `bad_cursor` |
| `page` (other than `1`) and `after` together — refused, as here, not resolved in favour of either | `page_and_after` |

### `?expand=` — admin only

`?expand=a,b` and `?expand=a&expand=b` both work. Named relation fields are
resolved to **depth one**, one batched query per field for the whole page.
Duplicates are dropped. A key that is not a relation field of the type is a
`400`. There is no depth greater than one, and the public API has no `expand`
at all.

### `?trashed=true` — admin only

Lists only the type's soft-deleted records. Costs `records.edit`, not merely
`records.view`.

### `?translations=true` — one record only

Lists the record's translation siblings on `GET …/records/{uuid}`. Never
honored on the list endpoint, where it would be one query per row.

### `?columns=` — the admin list screen only, not an API parameter

`/admin/records/{key}?columns=price,status,blurb` chooses which columns the
record-list *screen* shows, in that order (see the user guide's
[Columns](user-guide.md#columns)). It is read and written by the browser
alone: the view route ignores it, it changes nothing about which records
are returned, and **no JSON endpoint takes it** — the admin and public list
endpoints always return each record's full `data`, and `…/records/export`
always writes the full row. Keys are declared field keys or the record
columns `status`, `locale`, `position`, `published_at` and `updated_at`
(reserved field keys, so the two cannot collide); unknown keys are dropped
by the screen with a notice.

---

## Type endpoints

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/records/types` | `records.view` | List every type the caller may see |
| `POST` | `/api/records/types` | `records.manage_types` | Create a type |
| `GET` | `/api/records/types/{key}` | `records.view` (+ `allowed_roles` unless `manage_types`) | Read one type's definition |
| `PUT` | `/api/records/types/{key}` | `records.manage_types` | Update a type, including its schema |
| `DELETE` | `/api/records/types/{key}` | `records.manage_types` (+ `allowed_roles`) | Delete the type and every record of it, trash included |
| `GET` | `/api/records/types/{key}/export` | `records.view` (+ `allowed_roles` unless `manage_types`) | The definition alone, shaped for import |
| `POST` | `/api/records/types/import` | `records.manage_types` | Create or update a type from a definition |
| `POST` | `/api/records/types/{key}/reindex` | `records.manage_types` | Schedule a rebuild of the type's index rows |

### `GET /api/records/types` → `TypeListResponse`

`{"items": [TypeRead, …]}`. Types whose `allowed_roles` exclude the caller are
omitted.

### `TypeRead`

| Field | Type | Notes |
|---|---|---|
| `key` | string | Immutable |
| `label`, `label_plural` | string | |
| `description`, `icon` | string \| null | |
| `fields` | list of field objects | See [Field definitions](#field-definitions) |
| `schema_version` | int | Bumped by a change that affects payloads |
| `version` | int | Bumped by **every** write; what `expected_version` checks |
| `display_field`, `slug_field` | string \| null | |
| `collection` | string \| null | `null` means the shared tables |
| `is_public`, `show_in_menu`, `translatable` | bool | |
| `allowed_roles` | list of string | Empty means "not narrowed" |
| `record_count`, `trashed_record_count` | int | Live count |
| `reindex_pending` | object | `{field_key: ISO-8601 enqueued-at}`; the key `*` means the whole type |
| `created_at` | datetime | |
| `updated_at` | datetime \| null | |

### `POST /api/records/types` → `201 TypeRead`

Body is `TypeCreate`: `key`\*, `label`\*, `label_plural`, `description`, `icon`,
`fields`, `display_field`, `slug_field`, `is_public`, `show_in_menu`,
`translatable`, `allowed_roles`, `collection`. `collection` may be set **only
here**.

```bash
curl -s -b cookies.txt -X POST http://localhost:8000/api/records/types \
  -H 'Content-Type: application/json' -d '{
  "key": "article", "label": "Article", "label_plural": "Articles",
  "is_public": true, "display_field": "title", "slug_field": "title",
  "fields": [
    {"key": "title", "type": "text", "label": "Title", "required": true, "indexed": true},
    {"key": "body",  "type": "longtext", "label": "Body"},
    {"key": "views", "type": "integer", "label": "Views", "indexed": true},
    {"key": "topic", "type": "select", "label": "Topic", "indexed": true,
     "options": {"choices": [{"value": "news", "label": "News"},
                             {"value": "guide", "label": "Guide"}]}}
  ]}'
```

```json
{
  "key": "article", "label": "Article", "label_plural": "Articles",
  "description": null, "icon": null,
  "fields": [
    {"key": "title", "type": "text", "label": "Title", "required": true,
     "unique": false, "indexed": true, "default": null, "help": null,
     "constraints": {}, "options": {}}
  ],
  "schema_version": 1, "version": 1,
  "display_field": "title", "slug_field": "title", "collection": null,
  "is_public": true, "show_in_menu": false, "translatable": false,
  "allowed_roles": [], "record_count": 0, "trashed_record_count": 0,
  "reindex_pending": {},
  "created_at": "2026-09-21T14:17:45.698767Z", "updated_at": null
}
```

### Field definitions

Each entry of `fields`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `key` | string | required | `^[a-z][a-z0-9_]*$`, ≤ 64 chars, not reserved, immutable |
| `type` | enum | required | `text` `longtext` `number` `integer` `boolean` `date` `datetime` `select` `multiselect` `email` `url` `json` `media` `relation` |
| `label` | string | required | Non-empty, ≤ 200 chars |
| `required` | bool | `false` | On text-ish kinds, `""` and whitespace do not satisfy it |
| `unique` | bool | `false` | Normalizes `indexed` on. Refused on `multiselect`, `longtext`, `json`, `media` and on a to-many relation |
| `indexed` | bool | `false` | Refused on `longtext`, `json`, `media`. Forced on for `relation` |
| `default` | any | `null` | Coerced and validated against the field's own rules |
| `help` | string \| null | `null` | |
| `constraints` | object | `{}` | See below |
| `options` | object | `{}` | See below |

**Constraints**, by type:

| Types | Allowed keys |
|---|---|
| `text`, `longtext`, `email`, `url` | `min_length` (int ≥ 0), `max_length` (int ≥ 0), `pattern` (a valid regex) |
| `number`, `integer` | `min` (number), `max` (number) |
| everything else | none — any key is a `422` |

**Options**, by type:

| Type | Allowed keys |
|---|---|
| `select`, `multiselect` | `choices`: a non-empty list of `{"value": str, "label": str}` with unique, non-empty values |
| `relation` | `target_type` (a type key), `many` (bool, default `false`), `on_delete` (`restrict` \| `set_null` \| `cascade`, default `restrict`) |
| everything else | none — any key is a `422` |

Ceilings: `max_fields_per_type` (100) and `max_indexed_fields_per_type` (25).

**`media` values.** A `media` value is a string of at most 500 characters —
an opaque id or a URL; the API checks the length and nothing else, and never
looks the value up. What the admin UI stores in it is **the media library
file's id**: with the framework's `file_storage` module installed, the id
`POST /api/file-storage/upload` returns (a UUID, e.g.
`"3f0c6f8e-1d9b-4a57-9d7e-2c1b0f1e6a42"`). The file's address is not stored;
a client derives it from the id — `GET /api/file-storage/files/{id}/download`
on a stock host, the `file_url_template` the admin screens are handed (see
[operations.md](operations.md#media-library)).

The admin UI never asks the library about a value that is not shaped like one
of its ids (a UUID, with or without hyphens): only that shape is looked up. A
**plain `http(s)://` URL** saved before the picker existed stays a valid
value and renders as a link rather than being looked up. A **`/`-rooted
path** renders as a link too (a relative one), used as-is. Anything else —
free-form data from before the picker existed, or a seed/import that never
went through it, such as `"media/products/sku.png"` — renders as plain text,
also never looked up. Only an id-shaped value the library reports missing for
shows **File missing**; deleting the file in the media library does not
change any record, so the id stays and the UI shows that state instead.
Import and export treat the value as the text it is either way, so any of the
above round-trips unchanged.

### `PUT /api/records/types/{key}` → `TypeRead`

Body is `TypeUpdate`. `expected_version` is **required**; every other key is
optional and **only the keys actually sent are applied** — a body that does not
mention `allowed_roles`, `is_public` or `translatable` leaves all three alone.

Extra keys: `force` (bool, default `false`) applies a restrictive change and
marks the failing records; `orphaned` (`"restore"` | `"discard"`) resolves
re-added keys that still hold orphaned values.

`key` cannot change. A changed `collection` is a `409` (*"moving a populated
type between collections is not supported"*); an echo of the current value is
accepted.

### `DELETE /api/records/types/{key}?confirm_record_count=N` → `204`

`confirm_record_count` is **required** and must equal the type's current record
count (live plus trashed). A mismatch is `409`:

```json
{"detail": "type 'author' holds 1 record(s), not 99; reload and confirm again"}
```

This purges every record of the type, the trash included, and needs the type's
`allowed_roles` on top of `records.manage_types`.

### `POST /api/records/types/{key}/reindex` → `202`

```json
{"scheduled": true}
```

Schedules the type's pending rebuilds to run after the response. Idempotent.

---

## Record endpoints

All paths below are under `/api/records/types/{key}`.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/records` | `records.view` (+ `allowed_roles`; `trashed=true` costs `records.edit`) | List |
| `POST` | `/records` | `records.edit` (+ `allowed_roles`) | Create |
| `GET` | `/records/{uuid}` | `records.view` (+ `allowed_roles`) | Read one |
| `PUT` | `/records/{uuid}` | `records.edit` (+ `allowed_roles`) | Update |
| `DELETE` | `/records/{uuid}` | `records.edit` (+ `allowed_roles`) | Soft delete (trash) |
| `POST` | `/records/{uuid}/restore` | `records.edit` (+ `allowed_roles`) | Restore from the trash |
| `DELETE` | `/records/{uuid}/purge` | `records.edit` (+ `allowed_roles`) | Permanent delete |
| `POST` | `/records/bulk` | `records.edit` (+ `allowed_roles`) | One action over many records, all or nothing |
| `POST` | `/records/trash/empty` | `records.edit` (+ `allowed_roles`) | Purge the trash, or the filtered part of it |
| `GET` | `/records/aggregate` | `records.view` (+ `allowed_roles`) | Group and count |
| `GET` | `/records/export` | `records.view` (+ `allowed_roles`) | Stream JSON or CSV |
| `POST` | `/records/import` | `records.edit` (+ `allowed_roles`) | Import JSON or CSV |

### `GET /records` → `RecordPage`

Query: `page`, `page_size`, `after`, `total`, `filter`, `sort`, `trashed`,
`expand`.

`RecordPage`: `items` (list of `RecordRead`), `total` (int \| null), `page`,
`page_size`, `total_capped` (bool), `next_cursor` (string \| null).

```bash
curl -s -b cookies.txt \
  'http://localhost:8000/api/records/types/article/records?page_size=2&sort=-views&filter=topic:eq:news'
```

```json
{
  "items": [ { "uuid": "e489238d0c3c4ee995a159646a1ae642", "…": "…" } ],
  "total": 2, "page": 1, "page_size": 2, "total_capped": false,
  "next_cursor": "eyJoIjoiY2RkZDUyOTI5ZTgzIiwidiI6WyIwLjAwMDAwIiwxXX0"
}
```

### `RecordRead`

| Field | Type | Notes |
|---|---|---|
| `uuid` | string | 32 hex chars |
| `type_key` | string | |
| `data` | object | The payload, read leniently — defaults filled in, a record stamped at an older schema version read under the current one |
| `schema_stale` | bool | The record was written against an older schema version |
| `version` | int | What `expected_version` checks |
| `schema_version` | int | The schema version the record was written at |
| `status` | `"draft"` \| `"published"` | |
| `slug` | string \| null | |
| `locale` | string | |
| `translation_group` | string | 32 hex chars; the first sibling's uuid |
| `display_title` | string | Denormalized from the type's display field |
| `position` | int | |
| `published_at`, `created_at` | datetime / datetime \| null | |
| `updated_at` | datetime \| null | |
| `is_deleted` | bool | |
| `invalid` | list of `{field, message}` | What does not validate *right now*, per field. Costs a validator pass, so it is **always `[]` on a list response** — the single-record read is where it is filled |
| `invalid_since` | datetime \| null | When a scan last found this record wanting — the stored mark, filled on a list row too. Written by a forced schema change or by `rescan`; cleared by the record's next successful write — a restore is not one, since it validates nothing |
| `translations` | list of `TranslationRead` \| null | Only under `?translations=true` |
| `expanded` | object \| null | Only under `?expand=`; `{field_key: [ExpandedRef, …]}` in payload order |

### `POST /records` → `201 RecordRead`

Body is `RecordCreate`: `data` (object, default `{}`), `status`
(`"draft"` default), `slug`, `locale`, `position` (default `0`).

`locale` defaults to `default_content_locale`; a type that is not `translatable`
accepts only that one. An omitted `slug` is derived from the type's slug field.

```bash
curl -s -b cookies.txt -X POST \
  http://localhost:8000/api/records/types/article/records \
  -H 'Content-Type: application/json' \
  -d '{"data": {"title": "Hello 0", "views": 0, "topic": "news"}, "status": "published"}'
```

```json
{
  "uuid": "9d9addcbec0e46959ac5be78e15197e5", "type_key": "article",
  "data": {"title": "Hello 0", "body": null, "views": 0, "topic": "news"},
  "schema_stale": false, "version": 1, "schema_version": 1,
  "status": "published", "slug": "hello-0", "locale": "en",
  "translation_group": "9d9addcbec0e46959ac5be78e15197e5",
  "display_title": "Hello 0", "position": 0,
  "published_at": "2026-09-21T14:17:45.748333Z",
  "created_at": "2026-09-21T14:17:45.748470Z", "updated_at": null,
  "is_deleted": false, "invalid": [], "invalid_since": null,
  "translations": null, "expanded": null
}
```

### `PUT /records/{uuid}` → `RecordRead`

Body is `RecordUpdate`: `expected_version`\*, `data`\*, `status`, `slug`,
`position`. **`locale` is not honored** — a record's language is fixed for its
lifetime, and a body carrying one is a `422` rather than quietly dropped.

Publishing stamps `published_at` the first time; a record that is already
published keeps its original stamp through a status round trip.

### Delete, restore, purge

`DELETE /records/{uuid}` soft-deletes (trash) and answers `204`. It is refused
`409` while a `restrict` relation points at the record; `set_null` references
are cleared and `cascade` referrers are trashed with it.

`POST /records/{uuid}/restore` answers `200 RecordRead`.
`DELETE /records/{uuid}/purge` answers `204` and is permanent.

A trashed record keeps its slug claim and its `unique` claims until it is
purged or restored.

### `POST /records/bulk` → `BulkResult`

One action over many records. Body is `BulkRequest`:

| Field | Type | Notes |
|---|---|---|
| `action` | `"trash"` \| `"restore"` \| `"purge"` \| `"publish"` \| `"unpublish"` | Required |
| `uuids` | list of string | At least one, at most `max_bulk_records` (500); repeats collapse |
| `expected_versions` | `{uuid: int}` \| null | Optional and partial — a uuid it omits is applied at whatever version the row holds |

Every record goes through the same service call the single-record endpoint
makes, so `allowed_roles`, the `on_delete` cascade, slug and `unique` claims,
the revision log and the events are the single-record ones. `publish` and
`unpublish` write the record's own payload back with the new status, which
bumps its version and appends a revision exactly as an edit would; `trash`,
`restore` and `purge` leave the version alone and check `expected_versions`
without bumping it.

**All or nothing.** Every named record is attempted, every refusal is
collected, and if there is even one the whole batch is refused with a `409`
and *nothing is written*:

```json
{
  "detail": "2 of 5 record(s) refused trash; nothing was changed",
  "report": {
    "action": "trash",
    "requested": 5,
    "failed": [
      {"uuid": "9d9a…", "status": 409, "message": "3 record(s) still reference this record",
       "total": 3, "referrers": ["0b71…", "4c02…", "e5df…"], "hidden": 0, "more": 0},
      {"uuid": "0e13…", "status": 404, "message": "no article record with uuid '0e13…'"}
    ]
  }
}
```

`BulkFailure.status` is what that record alone would have answered — `404`
unknown, `403` `allowed_roles`, `409` a stale version or a `restrict`
relation, `422` a payload the current schema no longer accepts (a `publish`
of a record a forced schema change marked `invalid`). The batch's own status
is always `409`. The report is what a caller retries from: deselect what it
names, send the rest.

A run that refuses nothing answers `200 BulkResult`: `action`, `requested`
(distinct uuids), `changed`, `unchanged`, and `cascaded` — records a `trash`
reached through an `on_delete: cascade` relation and which the request never
named.

`unchanged` counts records already in the state the action asks for: a
`publish` of a published record, an `unpublish` of a draft. **Nothing is
written for them** — no version bump, no `update` revision, no
`RecordUpdated` — so "select all, Publish" no longer churns the history of
every record that was already published. `requested` is always
`changed + unchanged`. `trash`, `restore` and `purge` have no such case: a
record already in the trash is a *refusal* there, because those change a
record's existence and a caller acting on a stale list has to be told.

```bash
curl -s -b cookies.txt -X POST \
  http://localhost:8000/api/records/types/article/records/bulk \
  -H 'Content-Type: application/json' \
  -d '{"action": "publish", "uuids": ["9d9addcbec0e46959ac5be78e15197e5"]}'
```

```json
{"action": "publish", "requested": 1, "changed": 1, "unchanged": 0, "cascaded": 0}
```

One event per record, the same ones the single-record paths publish:
`RecordTrashed` (once per record a cascade reached, as always),
`RecordRestored`, `RecordPurged`, or `RecordUpdated` with the status
transition. A refused batch publishes nothing.

### `POST /records/trash/empty` → `TrashEmptied`

Purges every trashed record of the type. Takes the listing grammar's
`?filter=` — and nothing else, no `sort` or paging — so "empty what this
screen is showing" is the query the screen listed it with. `?trashed=true` is
not sent and not needed: this route is about the trash by definition.

```bash
curl -s -b cookies.txt -X POST \
  'http://localhost:8000/api/records/types/article/records/trash/empty?filter=topic:eq:news'
```

```json
{"purged": 12, "filtered": true}
```

Deliberately **not** bounded by `max_bulk_records`: the point of emptying the
trash is not having to name what is in it, and the purge is set-based rather
than a pass over records. It publishes one `RecordPurged` per record all the
same — that event is the only way a subscriber hears about a record that is
no longer there to read. A record still referenced by a `restrict` relation
is *not* a blocker here: it is already in the trash, which is where the
`restrict` check happened.

---

## Relation endpoints

### Forward — `?expand=`

```bash
curl -s -b cookies.txt \
  'http://localhost:8000/api/records/types/book/records?expand=writer'
```

```json
{
  "items": [{
    "uuid": "9bd09b7c3b984495a552d15f25ec7f94",
    "data": {"title": "A Wizard",
             "writer": {"type": "author", "uuid": "5082f5ca57a1417698e2ebffc6409ca9"}},
    "expanded": {"writer": [{
      "type_key": "author", "uuid": "5082f5ca57a1417698e2ebffc6409ca9",
      "display_title": "Ursula", "slug": null, "status": "draft",
      "dangling": false, "restricted": false}]}
  }],
  "total": 1, "page": 1, "page_size": 25, "total_capped": false, "next_cursor": null
}
```

`ExpandedRef` is in exactly one of three states:

| State | Means |
|---|---|
| **resolved** | `display_title`, `slug` and `status` are filled; `dangling` and `restricted` are `false` |
| **dangling** | The target is trashed, gone, or not a record of the declared type. `display_title` is `null`. A restorable delete must not break what references it, so this is a flag, not an error |
| **restricted** | The target's type narrows `allowed_roles` past the caller. Nothing but the uuid the caller already holds comes back |

Expanding a non-relation field is a `400`:

```json
{"detail": "'title' is not a relation field, so it cannot be expanded",
 "field": "title", "reason": "not_a_relation"}
```

### Reverse — `GET /records/{uuid}/referrers` → `ReferrersResponse`

Query: `page`, `page_size`. Permission: `records.view` plus `allowed_roles`.

```json
{
  "items": [{
    "type_key": "book", "type_label": "Book",
    "uuid": "9bd09b7c3b984495a552d15f25ec7f94", "display_title": "A Wizard",
    "field_key": "writer", "field_label": "Writer",
    "on_delete": "restrict", "is_deleted": false
  }],
  "total": 1, "hidden": 0
}
```

The three numbers mean different things:

- **`total`** counts every referring *record* — live, trashed, visible or not.
  One record pointing from two relation fields is one referrer and two `items`.
- **`hidden`** counts the ones whose type narrows `allowed_roles` past the
  caller. Stated rather than left to subtraction.
- **`items`** is the visible rows, paginated over the **visible set alone**, so
  walking pages cannot locate the hidden ones.

Trashed referrers are listed and flagged `is_deleted`; the delete path itself
ignores them. A trashed *target* answers too, for a caller holding
`records.edit`.

---

## Revision endpoints

| Method | Path | Permission |
|---|---|---|
| `GET` | `/records/{uuid}/revisions` | `records.view` (+ `allowed_roles`) |
| `GET` | `/records/{uuid}/revisions/{revision_id}` | `records.view` (+ `allowed_roles`) |
| `POST` | `/records/{uuid}/revisions/{revision_id}/restore` | `records.edit` (+ `allowed_roles`) |
| `GET` | `/types/{key}/revisions` | `records.view` (+ `allowed_roles` unless `manage_types`) |
| `POST` | `/types/{key}/revisions/{version}/restore` | `records.manage_types` |

`RevisionListResponse` is `{"items": [RevisionRead, …]}`. `RevisionRead`: `id`,
`version`, `schema_version`, `event` (`create` \| `update` \| `delete` \|
`restore`), `display_title`, `created_at`, `created_by`.

```json
{"items": [{"id": 1, "version": 1, "schema_version": 1, "event": "create",
            "display_title": "Hello 0", "created_at": "2026-09-21T14:17:51.649197",
            "created_by": "bace0701-15e3-5144-97c5-47487d543032"}]}
```

`GET …/revisions/{id}` returns `RecordRevisionDetailRead` — the same fields plus
`data`, the payload snapshot.

`POST …/revisions/{id}/restore` takes `{"expected_version": N}` and replays that
payload through the ordinary update path, so it is validated against the
*current* schema. Answers `200 RecordRead`.

`TypeRevisionRead`: `id`, `version`, `schema_version`, `fields`,
`display_field`, `slug_field`, `created_at`, `created_by`.

`GET /types/{key}/revisions` is **paged**, with the record list's own `page`
and `page_size` (clamped by `max_page_size`, defaulted by `default_page_size`)
— `{"items": [TypeRevisionRead, …], "total": N, "page": N, "page_size": N}`,
newest first. `total` is exact rather than capped by `max_count`: the count is
per type and cheap, and a "312+" would be useless to a panel whose job is to
find one particular past version. Type revisions are never pruned — they are
what a rollback reads, so a cap would eventually delete the version somebody
wants back — which is why the *response* is what is bounded. Unpaged, it grew
for the lifetime of the type and was re-downloaded on every open of the schema
screen (measured: 31 revisions of a four-field type is 24 KB, ~780 B each).

`POST /types/{key}/revisions/{version}/restore` takes `TypeRestoreRequest`
(`expected_version`\*, `force`, `orphaned`) and runs the rollback through the
schema-change pipeline — so it is classified, dry-run and refusable like any
other change.

How many record revisions are kept is `revision_limit` (50 by default, per
record); older ones are pruned on write.

---

## Translation endpoints

| Method | Path | Permission |
|---|---|---|
| `GET` | `/records/{uuid}/translations` | `records.view` (+ `allowed_roles`) |
| `POST` | `/records/{uuid}/translations` | `records.edit` (+ `allowed_roles`) |

`GET` returns a plain list of `TranslationRead` — `locale`, `uuid`, `status`,
`display_title`, `is_deleted` — covering the whole group, the record itself and
trashed siblings included.

```json
[{"locale": "en", "uuid": "3bbded82dce443c8a8141f5de1ca889d",
  "status": "published", "display_title": "Hello 0", "is_deleted": false}]
```

The same list is available on a record read as `?translations=true`. It is never
honored on the list endpoint, where it would be one query per row.

`POST` takes `TranslationCreate` — `locale`\*, `slug` (optional, ≤ 200 chars) —
and answers `201 RecordRead`. The sibling joins the source's
`translation_group`, copies its payload and `position`, starts as a **draft**
whatever the source's status, and gets a slug regenerated in the target locale
(suffixed `-2`, `-3`… if taken). An explicit `slug` is used as given and is a
`409` if taken in that locale.

Refusals: a type that is not `translatable` (`409`), a locale that is not
configured (`422`), a source already in the target locale (`409`), a sibling
that already holds that language (`409`) — **including a trashed one**, which
keeps its claim until it is purged or restored.

```json
{"detail": "type 'article' is not translatable; enable 'translatable' on the type before creating translations of its records"}
```

---

## Aggregate

`GET /api/records/types/{key}/records/aggregate` → `AggregateResponse`.
Permission: `records.view` plus `allowed_roles`. **Not available on the public
API, and will not be** — an anonymous aggregate is an oracle over rows the
caller cannot read.

| Parameter | Meaning |
|---|---|
| `group_by` | An indexed field, a virtual field, or a fixed column (`status`, `locale`, `slug`, `position`, `published_at`, `created_at`, `updated_at`, `display_title`, `invalid`) |
| `metric` | `count` (default), `sum:<number field>`, or `min:<field>` / `max:<field>` over a number, date, datetime or text field |
| `filter` | Repeats; means exactly what it means on the list |
| `locale` | Shorthand for `filter=locale:eq:<tag>` |
| `reduce` | Read a maintained aggregate instead of computing one — see [operations.md](operations.md#maintained-aggregates) |

```bash
curl -s -b cookies.txt \
  'http://localhost:8000/api/records/types/article/records/aggregate?group_by=topic&metric=sum:views'
```

```json
{
  "group_by": "topic", "metric": "sum:views",
  "groups": [
    {"value": "news",  "count": 2, "sum": "20.00000", "min": null, "max": null},
    {"value": "guide", "count": 1, "sum": "10.00000", "min": null, "max": null}
  ],
  "total_groups": 2, "truncated": false, "stored": false, "updated_at": null
}
```

Worth knowing:

- Every value comes back as a **string**, `count` excepted, so a live and a
  stored reading are comparable without per-field coercion.
- Groups are ordered by count descending, then by value, and capped at
  `max_aggregate_groups` (1,000) with `truncated: true`. What is dropped is
  always the long tail.
- **A multi-valued `group_by` counts a record once per value it holds**, so the
  counts sum to more than the number of records. That is the same reading
  `filter=tags:eq:red` has.
- The trash is never counted. A record with no value for the field is in no
  group at all; a *fixed column* that is `NULL` does produce a group whose
  `value` is `null`.
- `stored` is `true` and `updated_at` is set only for a `?reduce=` reading.
- Refusals are the filter grammar's: unknown field `400`, unindexed field `400`,
  mid-rebuild `409`, bad metric `400`.

---

## Schema-change endpoints

| Method | Path | Permission |
|---|---|---|
| `POST` | `/types/{key}/schema/preview` | `records.manage_types` |
| `GET` | `/types/{key}/schema/preview/{job}` | `records.manage_types` |

### `POST …/schema/preview`

Body is `SchemaPreviewRequest`: `fields`\*, `display_field`, `slug_field`,
`rescan`. Pointers only affect the diff when actually sent. Writes nothing.

`rescan: true` scans the records whatever the diff says. Without it a preview
whose `fields` are what is already stored has an empty diff, nothing in it is
restrictive, and the report short-circuits to `checked: N, failing: 0` — an
honest answer to "what would this change break" and a misleading one to "what
does not fit the schema now". Send the stored `fields` with `rescan: true` to
re-derive the worklist a `force`d restrictive change left behind; this is what
the type editor's **Check records** button does.

**With `rescan: true`, `fields` has to be the stored list.** This is the one
preview that *writes* — what the scan finds is recorded on each record's
`invalid_since` — and that mark is defined as the result of a scan of the
schema records are actually stored against. A `rescan` whose normalised
`fields` differ from the type's current ones is therefore refused with `422`
naming `fields`, before anything is scanned or marked; without the refusal any
caller could persist a worklist for a schema the type was never changed to.
Draft previews are unaffected: they write nothing, so they take any `fields`
at all. Above `preview_sync_limit` the scan is deferred, so the same refusal
reaches the caller as a failed job (`GET …/schema/preview/{job}` →
`{"status": "failed", "error": …}`) rather than as a `422`; nothing is marked
either way.

Up to `preview_sync_limit` records (5,000 by default) it answers `200` with
`SchemaPreviewRead`:

```json
{
  "kind": "restrictive",
  "changes": [{"kind": "restrictive", "field_key": "author",
               "what": "field_added", "before": null, "after": "text"}],
  "report": {
    "checked": 3, "failing": 3,
    "sample": [{"uuid": "9d9addcbec0e46959ac5be78e15197e5",
                "display_title": "Hello 0",
                "errors": [{"field": "author", "message": "Input should be a valid string"}]}],
    "orphaned_conflicts": {}, "duplicates": {}, "clean": false
  }
}
```

`duplicates` maps each key gaining `unique` to how many records already hold a
value another record holds. Those records are counted in `failing` as well, so
the change is refused without `force` like any other restrictive one; the map
is separate because `force` does not leave *these* recoverable — every other
marked record is fixed by its next ordinary write, and a duplicate cannot be
until one side's value changes or the field stops being unique.

`kind` is the most severe class in the diff: `additive`, `index_affecting`,
`restrictive`, `destructive`. `what` is a stable machine label —
`field_added`, `field_removed`, `type_changed`, `required_added`,
`required_removed`, `unique_added`, `unique_removed`, `indexed_on`,
`indexed_off`, `constraint_tightened`, `constraint_relaxed`, `choice_added`,
`choice_removed`, `options_changed`, `label_changed`,
`display_field_changed`. `sample` holds at most 10 failing records.

Above the limit it answers `202`:

```json
{"job": "0f2e…", "status": "running"}
```

Poll `GET …/schema/preview/{job}` → `SchemaPreviewJobRead`: `job`, `status`
(`running` / `done` / `failed`), `checked`, `total`, `preview`
(`SchemaPreviewRead` \| null), `error`. A `404` means this process no longer
holds the job — the registry is in-memory and bounded by design — and the answer
is to preview again, which writes nothing.

### Applying a change

`PUT /types/{key}` is where a schema change is applied:

- **additive** — applied immediately;
- **index-affecting** — applied immediately, with the affected keys added to
  `reindex_pending`; the rebuild runs after the response. Those fields refuse
  filters and sorts (`409`, `reason: "reindexing"`) until it clears;
- **restrictive** — refused `409` with the dry-run report unless every record
  passes; `force: true` applies it and *marks* the failures (they read back with
  `invalid` naming the fields) rather than rewriting them;
- **destructive** — the removed field's values move under the reserved
  `_orphaned` key on each record's next write. Re-adding a key that still holds
  orphaned values is a `409` until the caller sends `orphaned: "restore"` or
  `"discard"`.

```json
{
  "detail": "3 of 3 article record(s) would not satisfy the new schema; re-send with a default that makes them valid, or force=True to apply the change and mark them",
  "report": {"checked": 3, "failing": 3, "sample": [ … ], "orphaned_conflicts": {}, "clean": false}
}
```

A save straight after a preview does not scan twice: `PUT` reuses a completed
job's report when it was taken against the same type, the same proposed fields
and the same `version`, within `preview_job_ttl_seconds` (600). A save with no
matching preview, one sent with `rescan`, or one resolving orphaned keys with
`discard`, always runs its own pass.

---

## Domain events

Every write above also publishes on the framework's event bus — in-process,
after the request has committed, to whatever the host subscribed in its own
`register_event_handlers`. They are not part of the HTTP contract and a host
that subscribes to nothing never notices them; they are listed here because
they are the only way to observe a write without polling.

| Event | Published by | Carries |
|---|---|---|
| `RecordCreated` | `POST /records`, `POST …/translations`, each import row that created | `type_key`, `uuid`, `locale`, `translation_group`, `status` |
| `RecordUpdated` | `PUT /records/{uuid}`, `POST …/revisions/{id}/restore`, each import row that updated, each record a bulk `publish`/`unpublish` changed | `type_key`, `uuid`, `version`, `status_before`, `status_after` |
| `RecordTrashed` | `DELETE /records/{uuid}` and `POST …/records/bulk`, once per record the delete reached | `type_key`, `uuid`, `cascaded_from` |
| `RecordRestored` | `POST …/restore`, `POST …/records/bulk` | `type_key`, `uuid` |
| `RecordPurged` | `DELETE …/purge`, `POST …/records/bulk`, `POST …/records/trash/empty`, and once per record of a deleted type | `type_key`, `uuid`, `locale`, `translation_group` |
| `RecordTypeChanged` | `PUT /types/{key}`, `POST …/revisions/{v}/restore`, `POST /types/import` with `mode=update` | `type_key`, `schema_version`, `kind`, `index_affecting_keys` |
| `RecordTypeDeleted` | `DELETE /types/{key}` | `type_key`, `purged` |

Publishing is a status transition on `RecordUpdated` rather than an event of
its own, so a create-as-published is one event and not two. `cascaded_from` is
`null` for the record the caller named and its uuid for every record the
delete reached through a `cascade` relation. A refused write publishes
nothing, and neither does a dry-run import.

See
[architecture.md § Extension points](architecture.md#extension-points) for the
reasoning and the README for a worked subscriber.

---

## Import and export formats

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/types/{key}/records/export?format=json\|csv` | `records.view` | Streaming; takes the list's `filter`/`sort`; `trashed=true` costs `records.edit` |
| `POST` | `/types/{key}/records/import` | `records.edit` | Multipart `file=`, or a raw body with `Content-Type: application/json` / `text/csv` |
| `GET` | `/types/{key}/export` | `records.view` | The definition alone |
| `POST` | `/types/import` | `records.manage_types` | `mode=create` (default) or `mode=update` + `expected_version` |

### Record export

The response is a `StreamingResponse` with
`Content-Disposition: attachment; filename="<key>-<YYYY-MM-DD>.<ext>"` and
`Content-Type: application/json` or `text/csv; charset=utf-8`.

A refused `filter`/`sort` is the list's own `400`/`409`, decided **before** the
download starts — no truncated file named `200 OK`.

The export walks the type keyset-paged in batches of `reindex_batch_size` on a
session of its own, so a 100k-record type exports in constant memory. An export
with an explicit `?sort=` cannot be keyset-paged and uses `OFFSET` instead; the
unsorted default is what a round trip should use.

**What travels:** `uuid`, `slug`, `locale`, `translation_group`, `status`,
`position`, `published_at` and `data`. `data` is the lenient read, so defaults
are filled in and a record stamped at an older schema version exports under the
current one. Relations travel as stored (`{"type": …, "uuid": …}`), never
expanded. The reserved `_orphaned` key, the audit columns, `version` and
`is_deleted` do **not** travel: they describe this install's copy of the row.

#### JSON

```json
{
  "type": {"key": "article", "schema_version": 1, "fields": [ … ]},
  "records": [
    {"uuid": "3bbded82dce443c8a8141f5de1ca889d", "slug": "hello-0",
     "locale": "en", "translation_group": "3bbded82dce443c8a8141f5de1ca889d",
     "status": "published", "position": 0,
     "published_at": "2026-09-21T14:17:51.646610",
     "data": {"title": "Hello 0", "body": null, "views": 0, "topic": "news"}}
  ]
}
```

#### CSV

Seven envelope columns first, then one column per declared field in declaration
order. UTF-8 with **no** BOM, `\r\n` line endings per RFC 4180.

```csv
uuid,slug,locale,translation_group,status,position,published_at,title,body,views,topic
3bbded82dce443c8a8141f5de1ca889d,hello-0,en,3bbded82dce443c8a8141f5de1ca889d,published,0,2026-09-21T14:17:51.646610,Hello 0,,0,news
ea46a0ea9be54505bd471c2c5e59c2fd,hello-1,en,ea46a0ea9be54505bd471c2c5e59c2fd,published,0,2026-09-21T14:17:51.665467,Hello 1,,10,guide
```

Cell forms: a `number` is its decimal string, a boolean is `true`/`false`, a
date and a datetime are ISO. `multiselect`, `json` and `media` cells are
JSON-encoded. A relation is `type:uuid`; a to-many relation is a JSON list of
those. An empty cell means null.

> **CSV formula injection is escaped.** A cell beginning `=`, `+`, `-`, `@`, a
> tab, a carriage return **or an apostrophe** is written with a leading
> apostrophe. The importer strips exactly one leading apostrophe from every
> cell, so `export → import` is still exact — escaping the apostrophe itself is
> what makes that true. A CSV written by hand carries no doubling, so a
> hand-typed `'12` imports as `12`.

### Record import

Options come from the query string **and** from multipart form fields, the form
winning.

| Option | Values | Default | Meaning |
|---|---|---|---|
| `dry_run` | bool | **`true`** | Parse, validate and match every row; write nothing; return the full report |
| `mode` | `upsert` \| `create` \| `update` | `upsert` | What a row may do |
| `on_error` | `abort` \| `skip` | `abort` | `abort` rolls the whole request back and returns `422` with the report; `skip` writes the valid rows, each under its own savepoint |
| `match_by` | `uuid` \| `slug` \| a `unique` field key | `uuid` | How a row finds the record it updates |
| `force` | bool | `false` | Accept last-write-wins for a row carrying no `version` |
| `format` | `json` \| `csv` | guessed | From the explicit value, then the filename, then the content type |

Import is header-driven for CSV, so column order does not matter; a missing
column means "leave it alone", an empty cell means null.

`match_by=slug` slugifies the cell first, so `Hello World` matches the record
whose slug is `hello-world`. Matching on a field that is not `unique` is
refused:

```json
{"detail": "match_by='name' is not a unique field of 'author'",
 "errors": [{"field": "match_by", "message": "'name' is not unique"}]}
```

Matching on anything but `uuid` also refuses a row whose `uuid` already exists
but whose match key found nothing: the record's slug or unique value has moved
since the file was written, and creating it would collide on `uuid`.

**Response — `ImportReport`**, the same shape for a dry run, a real run and a
refusal:

```json
{"dry_run": true, "mode": "upsert", "total": 1,
 "created": 1, "updated": 0, "skipped": 0, "failed": 0,
 "errors": [], "errors_truncated": false, "duration_ms": 1}
```

`created + updated + skipped + failed == total`. `errors` holds at most 200
`ImportRowError` entries (`row`, `uuid`, `field`, `message`), with
`errors_truncated` saying the list is short while `failed` stays exact. `row` is
1-based and counts *data* rows — for CSV the header is not row 1.

**`skipped` is why re-importing an export is a no-op**: a row the record already
agrees with is not written at all, so versions do not move.

A row is refused for carrying `_orphaned`, naming an unknown field, pointing at
a relation target that does not exist, repeating a `uuid` already used earlier
in the same file, naming a `uuid` that belongs to another type or another table
set, matching a record in the trash, naming a translation group it may not join,
or updating a record without a `version`. **Every one of these is decided before
anything is written**, so a dry run and the apply that follows report the same
rows. The handful that genuinely cannot be predicted — a slug two rows of the
same file both derive — are reported against the row that failed, not row 0.

`translation_group` is carried verbatim but not taken on trust: a row that
*creates* a record may name only its own `uuid`, a group another row of the same
file also carries, or a group this type does not have yet.

A header naming a column the type has no field for is a `400` before any row is
read:

```json
{"detail": "the header names column(s) ['nope'] that this type has no field for"}
```

### Type export and import

`GET /types/{key}/export` → `TypeExport`: `key`, `label`, `label_plural`,
`description`, `icon`, `fields`, `display_field`, `slug_field`, `is_public`,
`show_in_menu`, `translatable`, `allowed_roles`, `collection`. Deliberately
`TypeCreate`-shaped: `record_count`, `version`, `schema_version` and
`reindex_pending` are facts about this install's copy and do not travel.

`collection` does, because it is a property of the definition rather than of
this install's copy: a collection-backed type exported without it landed on the
next install as a shared-tables type with no warning anywhere. On a create it
reaches `create_type`, so a name this host has not declared is the same `422`
`POST /types` gives; on `mode=update` a value that differs from the stored one
is the same `409` `PUT /types/{key}` gives, since a collection is assigned at
creation and never after. An echo of the current value is not a change and is
dropped, so re-importing this install's own export is unaffected.

`POST /types/import` takes `TypeImportRequest` — a `TypeExport` plus `mode`
(`create` default, or `update`), `expected_version`, `force` and `orphaned` —
and answers `200 TypeRead`. `mode=update` routes through the ordinary
`update_type` path, so importing a definition onto a populated type is
classified, dry-run and refused with the same report as the same change made in
the schema editor.

The update is built with `exclude_unset`: a definition that does not mention
`allowed_roles`, `is_public` or `translatable` leaves all three as they are. A
file that *does* name `allowed_roles`, and names a different list from the
stored one, costs the caller the type's own narrowing on top of
`records.manage_types`.

---

## Public read API

Off by default and per type. Setting `is_public` on a Record Type serves its
published records anonymously under `public_route_prefix`
(`/api/records/public` by default).

| Method | Path | Answers |
|---|---|---|
| `GET`, `HEAD` | `{prefix}/{type_key}` | `PublicRecordPage` |
| `GET`, `HEAD` | `{prefix}/{type_key}/{uuid}` | `PublicRecordRead` |

`PublicRecordRead` carries `uuid`, `slug`, `locale`, `display_title`,
`published_at`, `data` and `translations` — **nothing else**. The audit columns,
`version`, `status`, `invalid`, `invalid_since` and the reserved `_orphaned`
sub-key are removed from the *shape*, not filtered out of the query.

The public filter grammar does not answer about `invalid` either — a `400`
naming it, the same refusal an unindexed field gets. A public read is a read
of *published* records, and whether one of them is behind its schema is the
admin's problem: answering would let an anonymous caller count a type's
unhealthy records, and binary-search when they became unhealthy. The limits
(`max_filter_terms`, `max_sort_terms`, `max_in_values`, `max_count`) are
unchanged by any of this — `invalid` is one more fixed column, not a new kind
of term.

```bash
curl -s 'http://localhost:8000/api/records/public/product?page_size=2&sort=-published_at'
```

```json
{
  "items": [{
    "uuid": "a4aa3174655a46da8bf0e884068b8323",
    "slug": "sku-000059", "locale": "en",
    "display_title": "Portable Notebook",
    "published_at": "2026-09-21T07:21:13.934267",
    "data": {"sku": "SKU-000059", "name": "Portable Notebook",
             "category": "Tools & Hardware", "price": "1943.72",
             "in_stock": true, "tags": ["limited-edition", "staff-pick"]},
    "translations": [{"locale": "en",
                      "uuid": "a4aa3174655a46da8bf0e884068b8323",
                      "slug": "sku-000059"}]
  }],
  "total": 60, "page": 1, "page_size": 2, "total_capped": false,
  "next_cursor": "eyJoIjoiZWU2ZWRkODlhODY4IiwidiI6WyIyMDI2LTA5LTIxVDA3OjIxOjEzLjkyMzQ1NyIsMTgxXX0",
  "media_url_template": null
}
```

`media_url_template` (listing only) is how a site shows a `media` value: a
path with `{id}` in it when the host's media library serves files to
anonymous callers, and `null` when it does not. With `file_storage` it is
**always `null`**: that module exempts none of its routes from authentication,
and its download route also requires `file_storage.download`, so there is no
address an anonymous visitor could load a file from. The value is decided once
at startup, from the host's public-route registry
([architecture.md](architecture.md#media-library-detection)).

`translations` lists the record's **published, live** siblings — `locale`,
`uuid` and `slug` each — so a site can render a language switcher without
advertising an address that answers `404`. It is resolved in one batched query
per page. **On an install with a single content locale it is always `[]`**: a
record is alone in its own group, so no query is issued at all.

### How it differs from the admin API

**A type that is not public is a `404`, identical to one that does not exist**,
by key and by uuid alike. A draft, a trashed record and an unknown uuid answer
with the same body, so nothing here can be used to enumerate what an install
holds:

```bash
curl -s http://localhost:8000/api/records/public/company
```
```json
{"detail": "not found"}
```

**The filter and sort grammar is an allow-list.** Indexed declared fields, plus
`slug`, `display_title` and `published_at`. `status`, `position`, `created_at`,
`updated_at` and any virtual field are removed from the shape and therefore from
the grammar — otherwise an anonymous caller could binary-search an audit
timestamp it cannot read.

```json
{"detail": "cannot filter or sort by 'status'"}
```

Every refusal here is a plain `400` naming the field — **never the admin API's
`409`**, and never the admin's `field`/`reason` keys. "Cannot" and "cannot right
now" are the same answer to a caller with no business seeing operational state.

**`?locale=` names the language the listing is of, and its absence means
`default_content_locale` — never "all".** A locale that is not configured is a
`400` listing the ones that are:

```json
{"detail": "unknown locale 'de'; this site publishes in en"}
```

Resolution is case-insensitive (`?locale=DE` finds `de`). The **by-uuid route is
locale-blind** and ignores `?locale=`: a uuid names exactly one record in
exactly one language.

**No `?expand=` and no `?trashed=`** — they are simply not parameters here, and
unknown parameters are ignored.

**`page_size` is clamped to `max_page_size` rather than refused**, so an
anonymous caller probing the ceiling learns nothing and gets a usable page
either way.

`?after=`, `?total=false` and the `max_count` bound all apply, and a client
walking a large public type is exactly the caller that should use them.

**Both anonymous reads are cacheable.** They carry a weak `ETag` over the
content they are about to return and `Cache-Control: public, max-age=N`, where
`N` is the `public_cache_seconds` setting (60 by default). A conditional GET
whose `If-None-Match` matches is a `304` with no body, carrying the same
`ETag` and `Cache-Control` so a cache can refresh its entry. Comparison is
weak and `*` matches, per RFC 9110 §13.1.2. Setting `public_cache_seconds` to
`0` sends `Cache-Control: no-store` and no validator at all, which is the
setting for an install whose "published" means "visible the instant it is
saved".

The validator covers the *content*, so it changes when the answer does — a row
edited, a row unpublished out of the page, a different `?filter=`, a different
page of the same query — and not merely when some row somewhere was touched.

> **A shared cache still cannot store these responses on a stock host.** Every
> anonymous response also carries `Vary: Cookie` and a fresh
> `Set-Cookie: session=…` (the value decodes to `{"__i18n_locale": "en"}`),
> written on every request by `InertiaLayoutDataMiddleware` —
> `simple_module_hosting/_inertia_shared.py:54`. This module writes nothing to
> the session and does not work around it; until it is fixed upstream, these
> headers help a browser and a private cache rather than a CDN.

---

## Error table

**This table is `sm_records/endpoints/api/_error_table.py`.** The rows below
are that module's `ERROR_TABLE`, cell for cell and in order, and
`tests/test_openapi_errors.py` fails if either moves without the other — a
generated schema and a hand-maintained table are two descriptions of one
contract, and two descriptions drift. `GET /openapi.json` builds each
operation's `responses` from it, so every route documents the statuses its
kind of route can produce, with the body schema
(`sm_records/contracts/errors.py`) a generated client needs to parse them.

| Status | When | Body |
|---|---|---|
| `400` | A filter or sort naming an unknown field | `{"detail", "field", "reason": "unknown"}` |
| `400` | A filter or sort on a declared but unindexed field | `{"detail", "field", "reason": "not_indexed"}` |
| `400` | An operator the field's kind does not support | `{"detail", "field", "reason": "unsupported_op"}` |
| `400` | A filter value the field's kind cannot parse | `{"detail", "field", "reason": "bad_value"}` |
| `400` | `?expand=` naming a non-relation field | `{"detail", "field", "reason": "not_a_relation"}` |
| `400` | A malformed filter term, or `in` over `max_in_values` | `{"detail"}` |
| `400` | More than `max_filter_terms` / `max_sort_terms` terms | `{"detail"}` |
| `400` | `page` and `after` sent together | `{"detail"}` |
| `400` | A cursor that does not decode, or replayed under a different sort | `{"detail"}` |
| `400` | An import file that is not the format it claims, or a header naming an unknown column | `{"detail"}` |
| `400` | A filter term containing a NUL (`\x00`) character | `{"detail"}` |
| `400` | *Public API only* — any of the above | `{"detail"}` — no `field`, no `reason` |
| `401` | No session | `{"detail": "Not authenticated"}` — the framework's, not this module's |
| `403` | Missing `records.view` / `records.edit` / `records.manage_types` | `{"detail": "Permission required: records.edit"}` |
| `403` | The type's `allowed_roles` exclude the caller | `{"detail"}` — names the type and the roles, deliberately |
| `403` | *Multi-tenant hosts* — the signed-in account has no tenant of its own | `{"detail", "code": "tenant_required"}` — even when a tenant header was sent |
| `404` | Unknown type key, unknown uuid, a record in the trash on a non-trash read | `{"detail"}` |
| `404` | *Public API* — any of: unknown type, non-public type, draft, trashed, unknown uuid | `{"detail": "not found"}` |
| `404` | A preview job this process does not hold | `{"detail"}` |
| `409` | `expected_version` no longer matches | `{"detail", "current": RecordRead \| TypeRead}` |
| `409` | A slug or `unique` value already claimed (possibly by a trashed record) | `{"detail"}` |
| `409` | A delete blocked by `on_delete: restrict` | `{"detail", "total": n, "referrers": [uuid, …], "hidden": n, "more": n}` |
| `409` | A restrictive schema change that would leave records invalid | `{"detail", "report": DryRunReportRead}` |
| `409` | Re-adding a key that still holds orphaned values | `{"detail", "conflicts": {key: n}}` |
| `409` | A filter or sort on a field mid-rebuild | `{"detail", "field", "reason": "reindexing"}` |
| `409` | `DELETE /types/{key}` with a wrong `confirm_record_count` | `{"detail"}` |
| `409` | A changed `collection` on `PUT /types/{key}` | `{"detail"}` |
| `409` | A translation a type or a sibling will not allow | `{"detail"}` |
| `409` | Turning `translatable` off while records exist in another language | `{"detail"}` |
| `409` | A bulk action at least one named record refused | `{"detail", "report": BulkReport}` — nothing was changed |
| `413` | An import body over `max_import_bytes` | `{"detail"}` |
| `413` | An import file holding more rows than `max_import_rows` | `{"detail"}` — refused before anything is written |
| `413` | A bulk action naming more than `max_bulk_records` records | `{"detail"}` — refused before a record is touched |
| `413` | Any other `/api/records/*` write body over `max_payload_bytes` + 65,536 | `{"detail"}` — refused from `Content-Length`, before the body is read |
| `422` | A payload that does not satisfy the schema | `{"detail", "errors": [{"field", "message"}, …]}` |
| `422` | An invalid field or type definition | `{"detail", "errors"}` |
| `422` | `rescan: true` with `fields` that are not the type's stored ones | `{"detail", "errors"}` — nothing was scanned or marked |
| `422` | A NUL (`\x00`) in a payload value, a `unique` value, a type label or a field definition | `{"detail", "errors"}` |
| `422` | `locale` on `PUT /records/{uuid}` | FastAPI validation error |
| `422` | `match_by` naming a non-unique field; an unknown `format`; an undeclared `collection` | `{"detail", "errors"}` |
| `422` | `on_error=abort` and a bad row | `{"detail", "report": ImportReport}` |
| `422` | `page` outside `1 … 1000000`, `page_size` below 1 | FastAPI validation error |
| `422` | An empty `uuids` list, or an `action` that is not one of the five | FastAPI validation error |
| `500` | Anything unanticipated on `/api/records/*` | `{"detail": "internal error"}` — always JSON |

Worked examples:

```json
{"detail": "'nope' is not a field of 'article'", "field": "nope", "reason": "unknown"}
```
```json
{"detail": "'body' is not indexed, so it is not queryable", "field": "body", "reason": "not_indexed"}
```
```json
{"detail": "'title': gt is not valid on text", "field": "title", "reason": "unsupported_op"}
```
```json
{"detail": "too many 'filter' terms: 21 sent, at most 20"}
```
```json
{"detail": "title: Field required", "errors": [{"field": "title", "message": "Field required"}]}
```
```json
{"detail": "record 9d9addcbec0e46959ac5be78e15197e5 has changed since it was read",
 "current": {"uuid": "9d9addcbec0e46959ac5be78e15197e5", "version": 1, "…": "…"}}
```
```json
{"detail": "type 'book' is restricted to roles ['editor']; caller holds none of them"}
```
```json
{"detail": "1 record(s) still reference this record", "total": 1,
 "referrers": ["9bd09b7c3b984495a552d15f25ec7f94"], "hidden": 0, "more": 0}
```

The three `409`s a translation can meet are spelled out under
[Translation endpoints](#translation-endpoints): the type is not `translatable`, the source is
already in the target locale, or a sibling already holds that language.

A `restrict` refusal speaks the same three numbers the referrers panel does:
`total` counts every blocker, `referrers` lists at most 50 uuids of the ones
this caller may read, `more` says how many visible blockers were left off, and
`hidden` counts blockers whose type narrows `allowed_roles` past the caller —
counted, never named. `detail` says `total` again in a sentence, and
deliberately does **not** name the record being deleted: its uuid is in the
URL here and in `BulkFailure.uuid` in a batch, and a refusal panel that
printed it twice on one line had nothing left to say.

The same four keys ride on each entry of a bulk refusal's `report.failed`, so
a client has one shape to read whether it deleted one record or fifty. They
are absent (`null`) on every other kind of failure.

**Every refusal rolls the request's session back.** A refused delete that had
already cleared one `set_null` reference before meeting a `restrict` deeper down
commits nothing.

**The `allowed_roles` `403` names the roles, and that is deliberate.** A
`records.view` holder outside a type's list learns that the type exists — a
contrast with the `404` an unknown key gets — *and* the exact role names that
would grant access. It is a trade, made knowingly: the message is what an
admin debugging a permission needs, and the alternative (a `404` for a
narrowed type) makes a misconfigured `allowed_roles` indistinguishable from a
deleted type on every screen. Role names are otherwise install-private, so an
install that treats them as sensitive should read this row before relying on
narrowing as concealment: it narrows *access*, not *existence*.

**The `401` is the framework's, not this module's.** `AuthMiddleware` answers
an anonymous request to any `/api/*` path before a single route dependency
runs, so `{"detail": "Not authenticated"}` is what a caller with no session
actually receives — this table used to promise
`{"detail": "Authentication required"}`, which is the wording of the
*permission* dependency underneath it and is reachable only on an install
running no auth provider at all.

**A write body is refused before it is read.** `max_payload_bytes` bounds one
record's serialized `data`, which can only be measured after the whole request
has been read and parsed — so the module also bounds the *body*, from
`Content-Length`, at `max_payload_bytes` plus 64 KiB of envelope headroom, and
counts the bytes of a request that declares no length. That ceiling is
deliberately looser than the setting: it is the size past which a request is
not worth reading, while the route's own `422` remains the exact contract and
still names the precise number. `POST …/records/import` is exempt and keeps
`max_import_bytes`.

**Every `/api/records/*` response is JSON, including the ones nothing
planned for.** An unanticipated exception is logged with the request's
`x-correlation-id`, the request's session is rolled back, and the body is
`{"detail": "internal error"}` — never the SPA's HTML error document, which is
what an API client used to receive for a request that sent
`Accept: application/json`. The detail stays in the log: a stack-derived
message on an API is an information leak with no caller who can act on it.

The `/admin/records/*` **view** routes are the mirror of that rule: a refusal
there renders the host's error page, so a stale bookmark or a renamed type
shows the same 404 screen every other part of the app shows rather than a JSON
blob in the browser window.

**A NUL byte is refused wherever a string enters.** Postgres cannot store
`\x00` in `text`, `varchar` or `jsonb`, and its driver refuses to bind such a
parameter at all — so every one of these is a `4xx` naming the field rather
than the `500` the database would otherwise produce: a filter term (`400`), a
payload value including one nested inside a `json` document (`422`), a `unique`
value, an explicit slug (stripped by the slugifier, never stored), a type label
or `allowed_roles` entry, a field `label`/`help`/choice string, and an import
cell — that last as one `ImportRowError` naming the column, so `on_error=skip`
writes the rest of the file. A type key or record uuid in a *path* carrying one
is a `404`: no stored key or uuid can contain a NUL, so "no such thing" is
exact.

---

## Limits that bound a request

All are settings; see [operations.md § Settings](operations.md#settings).

| Setting | Default | Bounds |
|---|---|---|
| `default_page_size` | 25 | `page_size` when the caller sends none |
| `max_page_size` | 200 | `page_size` — clamped, not refused |
| `max_count` | 10,000 | How far `total` is counted exactly |
| `max_filter_terms` | 20 | `?filter=` terms per request — `400` over it |
| `max_sort_terms` | 5 | Distinct `?sort=` fields — `400` over it |
| `max_in_values` | 200 | Values in one `in:` list — `400` over it |
| `max_aggregate_groups` | 1,000 | Groups one aggregate returns, then `truncated: true` |
| `max_payload_bytes` | 262,144 | One record's serialized `data` |
| `max_payload_bytes` + 65,536 | 327,680 | Any `/api/records/*` write body except the import — `413` **before** the body is read |
| `max_import_bytes` | 52,428,800 | One import body — `413` **before** parsing |
| `max_import_rows` | 20,000 | Rows in one import — `413` **before** anything is written |
| `max_bulk_records` | 500 | Records one `POST …/records/bulk` may name — `413` **before** a record is touched |
| `public_cache_seconds` | 60 | `max-age` on an anonymous read; `0` is `no-store` |
| `max_fields_per_type` | 100 | Field definitions per type |
| `max_indexed_fields_per_type` | 25 | Indexed field definitions per type |
| `preview_sync_limit` | 5,000 | Records a preview dry-runs inside the request, then `202` |
| `revision_limit` | 50 | Revisions kept per record |
| — | 14 | Digits before the decimal point in a `number` **or** `integer` value — `422` over it |
| — | ±2,147,483,647 | `position` — the range its 32-bit column holds, `422` outside it |
| — | 32 | Nesting depth of one `json` field value — `422` over it |
| — | 10,000 | Values (scalars and containers) in one `json` field value — `422` over it |
| — | 1,000,000 | `?page=` — not a setting; an `OFFSET` that deep has nothing to find |
| — | 200 | `ImportReport.errors` entries |
| — | 50 | uuids listed in a `restrict` refusal |
| — | 10 | Failing records in a dry-run `sample` |

The two `json` bounds are not settings because there is no install they are a
policy decision for. `max_payload_bytes` bounds a payload's *size*, not its
*shape*, and the shape is what breaks: a few kilobytes nested three hundred
levels deep is a value the serializer refuses to render, so accepting it once
made every later read of that type a `500`. Both are checked on create, on
update and per import row (there, one `ImportRowError` naming the field, so
`on_error=skip` writes the rest of the file).
