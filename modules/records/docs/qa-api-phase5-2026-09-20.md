> **Point-in-time record.** The Phase 5 adversarial API review as delivered on 2026-09-20 against commit `da162c6`, kept verbatim as the evidence trail. The blocker, the three majors, the three minors and notes 1–3 were fixed in `cb82b08`; the durable regression tests are `tests/test_collision_uuid_sets.py`, `test_import_uuid_across_sets.py`, `test_import_groups_versions.py` and `test_public_grammar_locales.py`. Probe files were not kept.

# Phase 5 adversarial QA — `records` (smpy_modules @ `da162c6`)

Tree clean at "records: collections — a per-type document and index table set".
The module's own suite is green first (`804 passed, 43 deselected in 136s`), so
nothing below is a pre-existing red test.

Probes: `<scratchpad>/qa5/`,
run with
`cd /home/user/smpy_modules/modules/records && ../../.venv/bin/python -m pytest <file> -q -s -o asyncio_mode=auto -p no:cacheprovider`.
**65 probe tests: 57 assert the spec and pass, 8 fail — one per finding.**

---

## BLOCKER 1 — `on_delete` acts on the wrong record when one uuid exists in two table sets

`referrers()` looks up reference rows by `target_uuid` **alone**. §6.3 says the
ref row "stores `target_uuid` and `target_type_id`; the referrers query already
resolves the type" — it resolves the *referrer's* type, never the *target's*, so
`target_type_id` is written and never read. Inside one table set `uuid` is
unique so this is invisible; across sets it is not, and §6.4 admits "each record
table has its own unique index".

The precondition is not exotic. `write_row` keeps the file's uuid verbatim
(`created.uuid = row.uuid`, `_import_rows.py:203`) because §2 requires a round
trip to be idempotent. So **exporting a global type and importing it into a
collection type — the §12 "one type dwarfs the others, give it a collection"
motivation — plants the collision deterministically.** README §"`uuid` across
collections" blames "an importer that invents uuids some other way"; the
module's own importer is enough.

*Code:* `modules/records/sm_records/services/_relations.py`, in `referrers()`:

```python
select(ref.record_id, ref.field_key).where(ref.target_uuid == record.uuid)
```

*Spec:* Phase 5 §6.3 ("Cross-collection relations are allowed … the referrers
query already resolves the type"), §6.4.

### 1a. `cascade` trashes an unrelated record

`test_p2_uuid_collision.py::test_cascade_from_the_collection_record_trashes_the_wrong_records`

Setup: global `hall`, global `deal` with `spot -> hall, on_delete=cascade`,
collection type `gig` in `events`. One `hall` record, one `deal` pointing at it.
Then:

```
POST /api/records/types/gig/records/import?dry_run=false
{"records":[{"uuid":"<hall uuid>","data":{"name":"Clash"}}]}
-> 200 {"created":1,...}

DELETE /api/records/types/gig/records/<hall uuid>
-> 204

GET /api/records/types/deal/records/<deal uuid>
```

expected `200` (the deal points at the hall, which was never deleted)
actual `404 {"detail":"no deal record with uuid 'db6b16b2362348b4a5ce1ac670a804d4'"}`
— the deal was trashed by a cascade from a record it has no relationship with.

### 1b. `set_null` blanks an unrelated record's field

`test_p13_collision_rest.py::test_set_null_rewrites_a_record_that_points_elsewhere`

Same graph with `on_delete=set_null`:

```
DELETE /api/records/types/gig/records/<hall uuid>   -> 204
GET    /api/records/types/deal/records/<deal uuid>
```

expected `data.spot == {"type":"hall","uuid":...}`
actual `{'name': 'D1', 'spot': None}  version 2` — silently rewritten, version
bumped, a revision appended, and the hall it pointed at is still live.

### 1c. `restrict` blocks a delete nothing references

`test_p2_uuid_collision.py::test_deleting_the_collection_record_is_blocked_by_the_global_record_s_referrer`

```
DELETE /api/records/types/gig/records/<hall uuid>
```
expected `204` actual
`409 {"detail":"1 record(s) still reference aa30069d…","referrers":["d7ba888e…"]}`

### 1d. the referrers panel lists a foreign record

`test_p2_uuid_collision.py::test_referrers_of_the_collection_record_include_the_global_record_s`

```
GET /api/records/types/gig/records/<hall uuid>/referrers
```
expected `total: 0` actual
`{"items":[{"type_key":"deal","uuid":"ebc86f64…","display_title":"D1","field_key":"spot","on_delete":"restrict","is_deleted":false}],"total":1,"hidden":0}`

`?expand=` and the public by-uuid read are **not** affected — both predicate on
the declared target type's id inside that type's own table set
(`test_p13_collision_rest.py::test_expand_resolves_the_declared_target_s_table_only`,
`::test_public_by_uuid_is_not_confused_by_the_collision`, both pass). So the fix
is the one predicate `referrers()` is missing, not the model.

---

## MAJOR 2 — the same collision refuses legitimate relation writes

`test_p2_uuid_collision.py::test_a_new_relation_to_the_global_record_is_refused_after_the_collision`

`check_targets` builds `live: {uuid -> type_id}` by iterating `table_sets()` and
calling `live.update(...)`, so the **last** set to hold a uuid wins
(`_relations.py`, `check_targets`: `live.update({uuid: int(type_id) for …})`).

```
POST /api/records/types/deal/records
{"data":{"name":"D2","spot":{"type":"hall","uuid":"<hall uuid>"}}}
```
expected `201` actual
`422 {"detail":"record '3f90f226…' is not a 'hall'","errors":[{"field":"spot","message":"record '3f90f226…' is not a 'hall'"}]}`

The hall exists, is live, and is a hall. Every future write pointing at it is
refused because a record in a collection borrowed its uuid. Same root cause as
1, different code path — `live` needs to be keyed by `(uuid, type_id)` or
resolved per declared target type.

*Spec:* §6.4 ("`uuid` remains globally unique across collections"), §9.

---

## MAJOR 3 — the anonymous API filters, sorts by and returns index-provider virtual fields

`test_p12_virtual_public.py::test_anonymous_can_filter_and_sort_by_a_virtual_field`

`services/public.py::_check_columns` refuses only `_HIDDEN_COLUMNS =
FIXED_COLUMNS - PUBLIC_FIXED_COLUMNS`. Everything else falls through to
`index._filters.resolve`, which resolves **declared fields and virtual fields
alike**. A declared field's value is in `data` and therefore already public; a
virtual field's is not — §7.6 sells a provider as an additive *projection*, and
nothing puts it in `PublicRecordRead`.

Host registers `VirtualField("risk_score", NUMBER)` projecting a value that is
nowhere in the payload; type is `is_public`, records published:

```
GET /api/records/public/post
-> 200 … {"uuid":"7b12ce35…","slug":"a","locale":"en","display_title":"a",
          "published_at":…,"data":{"name":"a"},"translations":[…]}      # no risk_score

GET /api/records/public/post?filter=risk_score:gte:20
-> 200  items = ['b', 'c']                      # expected 400

GET /api/records/public/post?sort=-risk_score&page_size=1
-> 200  items = ['c'],
   next_cursor = "eyJoIjoiMTkxYWYxODJiZjY5IiwidiI6WyIzMC4wMDAwMCIsM119"
   base64-decoded: {"h":"191af182bf69","v":["30.00000",3]}
```

So the value is not merely oracle-able by binary search — `?after=` hands it
back **in clear**, to a caller with no session. That is verbatim the argument
`_fixed.PUBLIC_FIXED_COLUMNS` gives for removing `created_at`/`position`
("would let an anonymous caller binary-search an audit timestamp to arbitrary
precision"), applied to a column the host, not the module, invented.

*Spec:* §10 / `services/public.py` module docstring ("the admin one **narrowed
to the public shape**"); Phase 5 §3 ("it can show nothing the public API would
not").

*Code:* `modules/records/sm_records/services/public.py`, `_check_columns` — the
allow-list covers fixed columns only; `index/_cursor.py::encode_cursor` then
serialises the resolved sort value.

---

## MAJOR 4 — a forged `translation_group` in an import defeats `unique`

`test_p3_unique_slug_groups.py::test_a_forged_translation_group_in_an_import_shares_a_unique_value`

§5 of commit `8f1963b` / README: "`unique` is enforced among records that are
not siblings", implemented as `stmt.where(record.translation_group !=
exclude_group)` (`services/_claims.py::ensure_unique`). §2 makes the importer
carry `translation_group` "verbatim and never interpreted"
(`_import_rows.py::Envelope`). Nothing checks that the group the file names is
one this record has any business joining, and `RecordCreate` has no
`translation_group` precisely because it would be forgeable — the importer is
the same hole one door along.

Two content locales (`en`, `de`), type `art` with `sku` declared `unique`:

```
POST /api/records/types/art/records {"data":{"title":"One","sku":"SKU1"}}
-> 201, translation_group = aab03f351f5b4814b7baa9088ae44574

POST /api/records/types/art/records/import?dry_run=false
{"records":[{"data":{"title":"Impostor","sku":"SKU1"},
             "locale":"de",
             "translation_group":"aab03f351f5b4814b7baa9088ae44574"}]}
```
expected `created: 0` (an unrelated record may not join a group to dodge unique)
actual `200 {"created":1,"failed":0,"errors":[]}`, and

```
GET /api/records/types/art/records?filter=sku:eq:SKU1
-> [('aab03f351f5b4814b7baa9088ae44574','en'), ('13801975a9c34251adc50e671f1707ba','de')]
```

Two records now hold the `unique` value. Cost: `records.edit` on the type and a
second content locale — within one locale the `(translation_group, locale)`
index blocks it, so a monolingual install is not exposed. The honest reading is
that the group is a *capability* (it grants a uniqueness exemption) carried as
opaque data on an untrusted file. `_import_plan._immutable` already refuses a
row that tries to *move* an existing record between groups; a create is not
checked at all.

---

## MINOR 5 — `(translation_group, locale)` is unique per table set, not per type

`test_p3_unique_slug_groups.py::test_two_types_cannot_share_a_translation_group_and_locale`

`models/_record_args.py`: `Index(group_locale_index, "translation_group",
"locale", unique=True)` — no `type_id`. §4.3 states the rule as "One record per
`(translation_group, locale)`", and every reader of a group (`list_translations`,
`_sibling`, `published_siblings`) scopes by `type_id`, so the constraint is
wider than the concept it enforces.

```
# art record's group G, locale en. Importing an unrelated row into type `memo`:
POST /api/records/types/memo/records/import?dry_run=false&on_error=skip
{"records":[{"data":{"title":"Unrelated","sku":"S9"},"locale":"en",
             "translation_group":"<art's G>"}]}
```
expected `created: 1` actual
`{"created":0,"failed":1,"errors":[{"row":1,"message":"a memo record in 'en' already exists in that translation group"}]}`
— a refusal naming a record that does not exist. Reachable only through an
import that supplies groups (generated groups are uuid4s), so: confusing
refusal and a cross-type coupling, not corruption.

---

## MINOR 6 — an `on_error=abort` write-time failure is reported as `row: 0`

`test_p7_io.py::test_aborted_import_leaves_no_reduce_deltas`

Atomicity itself **holds** (see "held up"): the rollback discards both the record
and the reduce delta. But the report loses the row number:

```
POST /api/records/types/order/records/import?dry_run=false&on_error=abort
{"records":[{"data":{"name":"Dup","state":"ca"}},
            {"data":{"name":"Dup","state":"ca"}}]}
-> 422 {"detail":"import refused: slug 'dup' is already used by another order record in 'en'",
        "report":{"total":2,"created":0,"failed":1,
                  "errors":[{"row":0,"uuid":null,"field":null,
                             "message":"slug 'dup' is already used by another order record in 'en'"}]}}
```

`row: 0` is hard-coded in `services/import_.py::import_records`
(`errors.append(ImportRowError(row=0, message=exc.detail))`). §2's whole bargain
is that the caller "fixes the rows it names and re-posts the same file"; on a
40k-row file "row 0" names nothing. `_write` knows `plan.row.number`.

---

## MINOR 7 — removing a content locale orphans its records, with no guard

`test_p11_locale_decommission.py::test_dropping_a_content_locale_is_not_guarded`

§4.1 refuses turning `translatable` off while foreign-locale records exist,
because "those records become unreachable through a UI that no longer offers
their language" — verified, that guard works
(`::test_turning_translatable_off_with_foreign_records_is_refused` →
`409 "type 'article' holds 1 record(s) in a locale other than 'en'…"`).
`RecordsSettings.content_locales` has the same hazard and no such check
(`settings_checks.check_content_locales` only asserts non-empty and
default ∈ list). After an operator drops `de` on the Settings screen:

```
GET /api/records/public/article?locale=de     -> 400 {"detail":"unknown locale 'de'; this site publishes in en"}
GET /api/records/public/article/<de uuid>     -> 200  locale "de"
GET /api/records/public/article/<en uuid>     -> translations:
      [{"locale":"de","uuid":"85b8805d…","slug":"about-us"},
       {"locale":"en","uuid":"8350e671…","slug":"about-us"}]
PUT /api/records/types/article/records/<de uuid>   -> 200
```

The language switcher on the English page still advertises a language the
listing refuses to name, and the record stays publicly readable by uuid and
editable in the admin. Either state is defensible; the three disagree.

---

## NOTE 8 — the cursor signature does not cover `?locale=`

`test_p1_public_i18n.py::test_cursor_crossing_locales_on_public`

`sort_signature(type_key, sorts, trashed=…)` covers the type, the ordered
`(field, desc)` list and the trash flag. A public cursor taken under
`?locale=en` is accepted under `?locale=de` (`200`, page came back empty here).
No leak — the cursor is a keyset position and `_narrow_for` still applies the
locale predicate — but it is one more axis that "changes what the tuple means",
which is the criterion `index/_cursor.py` gives for the other three.

## NOTE 9 — the cursor signature does not cover the sort field's *kind*

`test_p1b_cursor_cross.py::test_cursor_after_the_sort_field_became_reindex_pending`

Cursor taken while `rank` was a `number` (`v: ["1.00000", 2]`), then `rank`
retyped to `text` and reindexed; replaying it is a `200` and `"1.00000"` is now
compared as a string. Here it happened to skip correctly; in general a retype
between two pages of a walk can skip or repeat rows silently. Bounded by F11's
own framing (the cursor is for exports and widgets, i.e. exactly the long
walks), so worth a line in the README if not a fix.

## NOTE 10 — the widget's anonymous client sends credentials

`utils/public-api.ts` documents itself as "no session, no cookie, callable from
a visitor who has never logged in", then calls
`fetch(url, { credentials: 'same-origin', … })`. Harmless — the public router
reads no `request.state.user` and its prefix is exempt from `AuthMiddleware` —
but the code and its docstring disagree, and `credentials: 'omit'` is what the
paragraph describes. Confirmed by reading; the widget's props are otherwise
client-side only and cannot reach past the public grammar
(`test_p10_admin_locale.py::test_public_api_refuses_status_and_position_filters`
and `test_p1_public_i18n.py::test_locale_filter_and_sort_are_refused_on_public`
cover the server side).

## NOTE 11 — a preview report shows record titles to a caller outside `allowed_roles`

`POST /types/{key}/schema/preview` uses `load_type`, not `load_allowed_type`
(deliberately: §10 keeps `manage_types` able to open the schema screen). The
report carries `checked` and up to `DRY_RUN_SAMPLE=10` `FailingRecord`s with
`uuid`, `display_title` and validator messages. Pre-existing §8.9 behaviour, not
introduced by F10 — the job handle adds no reach, since the same caller can
re-run the preview. Flagged only because the job now keeps that report in
memory for `preview_job_ttl_seconds` behind a `manage_types`-only handle.

## NOTE 12 — `?reduce=` reports `metric: "sum:<spec key>"`

`services/aggregate.py::stored_aggregate`: `metric="count" if spec.value is None
else f"sum:{key}"`. On the live reading `sum:<x>` names a *field*; here it names
the spec. Observed: `{"group_by":"by_state","metric":"sum:by_state",…}`. Cosmetic,
but it is the one string a caller comparing the two readings would diff.

---

## Held up

Everything below was probed and behaved as §§1–6 say it should.

**Public API / i18n** (`test_p1_public_i18n.py`, `test_p1b_cursor_cross.py`,
`test_p9_…`, `test_p10_admin_locale.py`)
- `filter=locale:eq:de` and `sort=locale` on the public list: `400 "cannot filter
  or sort by 'locale'"` — the default-locale rule cannot be filtered around.
- `status`, `position`, `created_at`, `updated_at`: refused as filter *and* sort,
  same flat 400.
- `?locale=fr` → `400 "unknown locale 'fr'; this site publishes in en, de"`;
  `?locale=DE` resolves case-insensitively.
- `translations` on the public shape lists published live siblings only — a draft
  sibling and a trashed sibling are both absent; `status`/`position` absent from
  the shape.
- `/public/{type}/aggregate` → `404`, `POST` → `405`.
- `page_size=100000` clamped to 200; `max_count` capping applies per `?locale=`
  on both halves (en `1/true`, de `1/true`).
- cursor replayed on another type → `400`; from the trash listing onto the live
  one → `400 "cursor was produced under a different sort order"`; malformed →
  `400`; tampered digest → `400`; after the type went private → `404`.
- `?page=2&after=…` → `400`; `?trashed=`/`?expand=`/`?translations=` ignored on
  the public list; `?translations=true` never filled on the admin list.
- a public type inside a collection lists, reads by uuid and honours `?locale=`.
- a private type's record is only ever a stored `{"type","uuid"}` in a public
  payload; `GET /public/secret/{uuid}` is the shared `404`; `?expand=` adds
  nothing to the public body.

**Uniqueness / slugs / groups** (`test_p3_…`, `test_p13_…`)
- same slug in two locales inside a collection type: both `201`; the second `en`
  one `409 "slug 'launch' is already used by another gig record in 'en'"`.
- a translation copies the source's `unique` SKU (`201`); an unrelated `de`
  record with that SKU `409`.
- `POST /translations` into a language a **trashed** sibling holds:
  `409 "…in the trash (…); restore or purge it rather than creating a second"`,
  and the panel reports `('de', is_deleted=True)`.
- `match_by=slug` scoped per locale (the German row updated the German record,
  the English one untouched) and per table set (a collection import did not
  touch the identically-slugged global record).
- `match_by=uuid` is per table set, as deviation 8 says.

**Reduce / aggregates** (`test_p4_…`, `test_p5_…`, `test_p8_…`)
- transitions: create `+1`, same-group edit no change, group move `-1/+1`, trash
  `-1`, restore `+1`, purge-after-trash no double decrement.
- a `set_null` cascade moves the referrer between groups.
- a schema retype on the grouped field leaves the fold consistent (the payload
  is migrated lazily, so old and new sides agree).
- a spec raising on the **old** side over-counts (`{'ca':1,'ny':1}` for one
  record) — exactly what `reduce.contribution`'s docstring promises, and what the
  verifier is for.
- 8 concurrent creates into one group on a **file-backed** SQLite: `8×201`,
  stored row `('ca', 8, Decimal('8'))` — no lost increment.
- injected drift (`count += 5`) is found by `verify_type`
  (`order/by_state group 'ca': stored (8, None), records say (3, None)`),
  surfaces as the `reduce_drift` health detail, and `rebuild_type` clears both;
  a re-verify is clean. A decrement with no stored row inserts no negative row.
- `?reduce=` works on a collection type and refuses `group_by`/`metric`/`filter`/
  `locale` alongside it (`400` each); an unregistered key is `400`, not an empty
  result.
- `allowed_roles` narrows the aggregate (editor `200`, second editor `403`,
  anonymous `401`).
- `group_by=translation_group` → `400 "not a field"`; so are `uuid`, `version`,
  `data`, `is_deleted`, `type_id`, `id`. `locale`/`status`/`slug`/`position`/
  timestamps group as fixed columns.
- `filter` + `group_by` on the same field agree; `sum`/`group_by` over a virtual
  field work; `truncated` flips exactly at `max_aggregate_groups` (cap 3 of 3 →
  false, cap 2 of 3 → true); the trash is never counted.

**Perf** (`test_p6_perf.py`)
- F4 with trash present: 3 live + 5 trashed, cap 3 → `(3, false)`; cap 2 →
  `(2, true)`; cap 4 → `(3, false)`; the trash listing at cap 3 → `(3, true)`.
  The inner `LIMIT` does not fill with trashed rows.
- `starts_with` on `\U0010FFFF` returns the row (`prefix_range` → `(term, None)`,
  upper bound dropped); `prefix_range(chr(0xD7FF))` steps to `0xE000`;
  `prefix_range("a\U0010FFFF")` → `"b"`. (A lone surrogate is unreachable — httpx
  cannot encode it into a URL.)
- preview jobs: `202` + poll → `done`; job id is a 32-hex uuid4; `records.view`
  → `403`, anonymous → `401`; job read under another type's URL → `404`;
  `reusable()` returns the report at the recorded version, `None` one version
  later, `None` at `ttl=0`; 60 finished jobs prune to 50; an expired job is
  dropped on the next `start`.

**Import / export** (`test_p7_io.py`, `test_p9_…`)
- `on_error=abort` rollback with a reduce spec registered: `422`, 0 records,
  **0 reduce rows** — the delta rolled back with the write.
- a CSV `locale` cell naming a non-content locale is that **row's** error
  (`{"row":1,"field":"locale","message":"'fr' is not a content locale"}`), not
  the file's.
- `_orphaned` as a CSV column → `400 "the header names column(s) ['_orphaned']…"`;
  inside a JSON `data` → row error `"'_orphaned' is reserved and cannot be
  imported"`.
- a global export imports into a collection type and re-exports with
  `uuid,slug,locale,translation_group,status,position,published_at,…`.
- size cap: exactly `max_import_bytes` → `200`; one byte over → `413 "the
  uploaded file is 15 bytes, over the 14-byte limit"`.
- `errors_truncated`: exactly `ERROR_CAP` (200) errors → `false`; 205 → `true`
  with 200 carried.
- an export streaming while the type's schema changes under it keeps the
  snapshot it started with: 6 records, `data` keys `['name','state']` after
  `state` was dropped mid-stream.

**Widget** — `puck-blocks.ts` registers one block; `RecordsListRender` only ever
calls `fetchPublicRecords` with `prefix`/`typeKey`/`limit`/`filter`/`sort`/
`locale`; `buildPublicListUrl` sets `page_size`, `filter`, `sort`, `locale` and
nothing else; `fields` never leaves the client. Nothing server-side beyond the
public API — so the block inherits MAJOR 3 and nothing of its own.

---

## Totals

| severity | count |
|---|---|
| blocker | 1 (with four distinct symptoms) |
| major | 3 |
| minor | 3 |
| note | 5 |

Probe files: 14. Probe tests: 65 — 57 pass (spec holds), 8 fail (one per
finding). Module suite at HEAD: 804 passed, 43 deselected.

