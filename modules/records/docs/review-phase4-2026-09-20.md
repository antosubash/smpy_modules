> **Point-in-time record.** The adversarial review of the Phase 4 backend (commits `ce02637`, `7e2948b`, `5b6fb36`) as delivered on 2026-09-20, kept verbatim as the evidence trail. B1, M1–M4, m1–m7 and notes n1/n2 were fixed in `e8c1ff8`; the durable regression tests are `tests/test_review_fixes_round4*.py`. The `test_*_probe.py` files referenced here asserted the *old* behaviour and were not kept. Two decisions the fixes encode: `allowed_roles` narrows reads as well as writes (M1), and a stored reference whose type disagrees with the field's declared target is `dangling` (M2).

# Phase 4 ("reach") adversarial review — `records`

Scope: commits `ce02637`, `7e2948b`, `5b6fb36` on `claude/json-module-crud-plan-rr9iam`,
Python only (the working tree's `.tsx`/`locales`/e2e edits were ignored; every file below
was read from the commits, not the worktree).

Probes: `<scratchpad>/review4/`
(`conftest.py` imports the module fixtures *including* `_clear_model_cache` and
`_clean_providers`). Run with:

```
cd /home/user/smpy_modules/modules/records && \
  ../../.venv/bin/python -m pytest <scratchpad>/review4/ -q -s -o asyncio_mode=auto -p no:cacheprovider
```

55 probes, all green — every probe asserts the behaviour actually observed, buggy or correct.

---

## BLOCKER

### B1. A registered index provider whose virtual key collides with an existing type's declared field key takes that type completely offline — every read, every write, and the anonymous public endpoint

*Probe:* `test_providers_probe.py::test_a_shadowing_virtual_key_makes_every_read_of_that_type_a_422`
and `::test_the_same_shadow_takes_the_public_site_down_too`

```
GET /api/records/types/product/records                    (before register)  -> 200
# host module calls register_index_provider(p, fields=[VirtualField("bucket", TEXT)])
GET  /api/records/types/product/records                   -> 422
GET  /api/records/types/product/records/{uuid}            -> 422
GET  /admin/records/product          (Inertia)            -> 422
PUT  /api/records/types/product/records/{uuid}            -> 422
GET  /api/records/public/product     (anonymous)          -> 422
```

Body, identical on all five:

```json
{"detail":"type 'product' has an invalid field definition: field 'bucket': key is reserved by an index provider: it is a virtual field, queryable on every type's records, so a declared field of the same key would shadow it","errors":[{"field":"bucket","message":"key is reserved by an index provider: it is a virtual field, queryable on every type's records, so a declared field of the same key would shadow it"}]}
```

*Expected:* exactly what `7e2948b`'s commit message and `index/query.py:113-137`
(`_resolve`) promise — "Declared keys win over a same-named virtual key (only possible
for a type stored before the provider registered) with one WARNING per type", because
"refusing its filter — or answering it from the provider's rows — would break a type that
works".

*Actual:* `schema/_keys.py:63-69` (`validate_key`) refuses the declared key
unconditionally, and **every** read and write goes through it:
`contracts/public.py` → `services/_payload.read_view` → `_payload.field_defs`
(`_payload.py:42-48`) → `validate_fields` → `validate_key`. The shadow-tolerating branch
in `_resolve` is therefore unreachable in practice — the request 422s before a filter is
ever compiled. `7e2948b` introduced both halves, so the two contradict each other inside
one commit.

Worst case for a distributed module: a host ships an add-on that registers
`VirtualField("title")` or `VirtualField("name")`; on the next deploy every Record Type
declaring that key — including public ones serving a live site — answers 422 to everyone,
with no way back except unregistering the provider or hand-editing `records_type.fields`.

Spec: §7.6 (providers are an extension point that must not touch storage or existing
types); README "Extending the index" (added in `7e2948b`) documents the refusal only for a
*new* declaration, not for existing ones.

---

## MAJOR

### M1. `restricted` on `?expand=` and the referrers redaction protect nothing: the same caller reads the narrowed type in full one request away

*Probe:* `test_roles_probe.py::test_a_redacted_target_is_readable_in_full_one_request_away`

Type `author` has `allowed_roles: ["records-editor"]`; caller holds `records-viewer`
(`records.view` only).

```
GET /api/records/types/book/records/{book}?expand=author   X-Test-Roles: records-viewer
-> 200 {"expanded":{"author":[{"type_key":"author","uuid":"480d…","display_title":null,
        "slug":null,"status":null,"dangling":false,"restricted":true}]}}

GET /api/records/types/author/records/{author}             X-Test-Roles: records-viewer
-> 200 {"uuid":"480d…","type_key":"author","data":{"name":"Secret Author"},…,
        "display_title":"Secret Author",…}

GET /api/records/types/author/records                      X-Test-Roles: records-viewer
-> 200 total=1
GET /admin/records/author  (Inertia)                       X-Test-Roles: records-viewer
-> 200 (full list props)
```

*Expected:* the README paragraph this very commit added
(`5b6fb36`, README ≈ line 201): "**`allowed_roles` narrows reads as well as writes, but it
narrows them differently.** A caller the list excludes is *refused* a write and is
*redacted* on a read."

*Actual:* `check_type_roles` (`deps.py:113-136`) is called only on the write routes
(`endpoints/api/records.py` create/update/delete/restore/purge). `list_records`
(`records.py:62`) and `get_record` (`records.py:137`) carry `dependencies=[require_view]`
and nothing else, and `endpoints/views.py` likewise. So the narrowing is a *write* rule
only; Phase 4's read-side redaction hides `display_title` in one place and serves it in
another. `deps.check_type_roles`' own docstring claims the opposite ("so the read surface
cannot be more permissive than the write surface").

Consequences either way it is resolved:
* as security, `restricted`/referrer redaction is cosmetic — no confidentiality is gained;
* as UX, it is actively bad: `test_extras_probe.py::test_the_admin_wildcard_is_redacted_on_expand_too`
  shows even an `admin` caller gets `restricted: true` in the list and editor screens for a
  record they can open in the next tab (README says narrowing has no wildcard exception).

Not a new hole opened by Phase 4 — the read routes were ungated before — but Phase 4 is
what documents the guarantee and builds UI on it, so it is the commit that has to pick one
story.

### M2. `?expand=` resolves a stored reference by uuid alone, with no type predicate, while `restricted` is decided from the *declared* target

*Probe:* `test_expand_probe.py::test_a_stored_ref_whose_type_disagrees_with_the_declared_target`

`book.author` declares `target_type: "author"` (unrestricted). A stored payload — the
kind `index/providers.py:_ref_entry` explicitly says exists, "for rows written before that
check existed" — holds `{"type":"secret","uuid":…}` where `secret` has
`allowed_roles: ["records-editor"]`:

```
GET /api/records/types/book/records/{book}?expand=author   X-Test-Roles: records-viewer
-> 200 …"expanded":{"author":[{"type_key":"secret","uuid":"a61f…",
       "display_title":"Top Secret","slug":null,"status":"draft",
       "dangling":false,"restricted":false}]}
```

*Expected:* §9/§10 and `services/expand.py`'s own docstring — "decided from the field's
declared `target_type` alone. Nothing about the row is read".

*Actual:* `expand.py:170` computes `restricted` from the declared target, `expand.py:78`
(`_refs`) echoes the *payload's* `type`, and `expand.py:125` (`_targets`) selects
`Record.uuid.in_(uuids)` with no `type_id` predicate at all — so the row that is read can
belong to any type in the install, including one the declared-target check cleared. The
returned `ExpandedRef` then advertises `type_key: "secret"` with `restricted: false`, which
is self-contradictory on its face.

Two mitigations keep this out of "blocker": today's writes cannot create the mismatch
(`_relations.check_targets`), and M1 means the caller could read it anyway. The variant
where the relation definition names *no* target is closed for a different reason —
`field_defs` re-validation 422s the whole read
(`test_expand_probe.py::test_a_relation_definition_with_no_target_type_is_refused_at_read`).
The fix is one `Record.type_id ==` predicate in `_targets`, keyed off the type the
`restricted` decision was made against.

### M3. `public_route_prefix` is unvalidated; a parent-path value hands the whole admin surface to `AuthMiddleware`'s exemption, and a value without a leading `/` kills the lifespan

*Probe:* `test_boot_probe.py::test_prefix_equal_to_the_admin_api_exempts_the_whole_admin_surface`,
`::test_an_empty_prefix_exempts_every_get_in_the_host`,
`::test_a_prefix_without_a_leading_slash_kills_the_lifespan`,
`::test_dir_prefix_normalisation_table`

```
public_route_prefix = "/api/records"
  rules: [PublicRoute('/api/records/', kind='prefix', methods=GET,HEAD)]
  GET /api/records/types                              exempt -> True
  GET /api/records/types/article/records              exempt -> True
  GET /api/records/types/{k}/records/{u}/referrers    exempt -> True
  GET /api/records/types/{k}/records/{u}/revisions    exempt -> True

public_route_prefix = ""            (dir_prefix("") == "/")
  rules: [PublicRoute('/', kind='prefix', methods=GET,HEAD)]
  GET /admin/users          exempt -> True
  GET /admin/settings       exempt -> True
  GET /api/pagebuilder/pages exempt -> True
  GET /                      exempt -> True

public_route_prefix = "api/records/public"
  on_startup raised: AssertionError  A path prefix must start with '/'
```

*Expected:* §10 — "the fixed `/api/records/public/` prefix cannot match the admin surface".
The prefix is no longer fixed, and `settings.py:58`'s docstring asserts "a value sharing
its first characters with the admin API (`/api/records`) is therefore still safe".

*Actual:* `boot.dir_prefix` (`boot.py:32`) only adds a trailing `/`; nothing rejects a
prefix that is a *parent* of the admin API or of the host root, and `boot.dir_prefix`'s own
docstring admits `/api/records` "would hand the entire admin API to anonymous callers".
`RecordsSettings` (`settings.py:58`) applies no validator — the Settings screen accepts any
string. Defence in depth holds *for this module* (every admin route carries
`RequiresPermission`, so an anonymous caller still gets 401), but the exemption is
host-wide: it disables `AuthMiddleware` for every `GET`/`HEAD` under the prefix, including
other modules' routes that rely on the middleware rather than on their own dependency —
exactly what `register_public_routes` exists to scope. The empty/`/` case is the worst:
one blank field on the Settings screen exempts the entire host, and only a restart
(`requires_restart`) undoes it.

Separately, a leading-slash typo turns the lifespan into an `AssertionError` — the app
fails to boot and the only cure is a DB edit, because the value is only reachable through
the app that will not start. A `field_validator` (must start with `/`, must not be a
prefix of `ROUTE_PREFIX_API` or `VIEW_PREFIX`, must not be `/`) costs five lines.

### M4. A null (or any non-ref item) in a to-many relation payload silently misaligns `expanded` with `data`

*Probe:* `test_expand_probe.py::test_a_null_in_a_to_many_list_misaligns_expanded_with_data`

```
POST /api/records/types/book/records
  {"data":{"name":"B","author":[{…uuid A},null,{…uuid B},{…uuid A}]}}   -> 201  (accepted)

GET  …/records/{uuid}?expand=author -> 200
data     : [{A},null,{B},{A}]                     len 4
expanded : [A("One"), B("Two"), A("One")]          len 3
```

*Expected:* `expand._refs`' docstring, which states the contract the UI depends on — "``(type key, uuid)``
per stored reference, **in payload order**… A to-many field's expansion has to line up with
``data[key]`` positionally — the UI renders the two together".

*Actual:* `expand.py:78-95` skips items that are not dicts with a `uuid`, so the list
shortens and every entry after the hole is off by one; `expanded[1]` is the title of
`data[2]`. The record editor and list screen render the two zipped, so a null in the middle
of a to-many list mislabels every following picker entry. Payload validation accepts the
null (201 above), so this is reachable through the public write API with no DB surgery.
Duplicates, by contrast, are handled correctly (kept in both, one query).

---

## MINOR

### m1. The referrers page window is taken before the role filter, so `page_size=1` is an exact oracle for which referrers are hidden

*Probe:* `test_referrers_probe.py::test_paging_is_an_oracle_for_which_positions_are_redacted`

Four referrers, slots 2 and 4 in a type the caller is excluded from:

```
GET …/referrers?page=1&page_size=1  -> {"items":[{… "O1"}],"total":4}
GET …/referrers?page=2&page_size=1  -> {"items":[],"total":4}
GET …/referrers?page=3&page_size=1  -> {"items":[{… "O2"}],"total":4}
GET …/referrers?page=4&page_size=1  -> {"items":[],"total":4}
slots the excluded caller can prove are hidden: [2, 4]
```

`_relations.paged_referrers` (`_relations.py:192-223`) documents "nothing about it leaks,
not even its type" — the position does leak, and since the list is `sorted(pairs)` on
`(record_id, field_key)`, the positions order the hidden records by insertion order
relative to the visible ones. Given that `total` already publishes the count by design,
this is an increment rather than a new class of leak, but the docstring overstates the
guarantee.

### m2. `referrer_count` (the editor badge) and the panel's `total` disagree in three reachable ways

*Probe:* `test_referrers_probe.py::test_referrer_count_badge_disagrees_with_the_panel`,
`::test_badge_counts_referrers_the_panel_will_never_show`,
`::test_a_referrer_row_whose_record_vanished_behind_the_module`

| case | badge (`_relations.referrer_count`, `_relations.py:225`) | panel `total` | panel `items` |
|---|---|---|---|
| one record referencing the target from two relation fields | 1 | 2 | 2 |
| three referrers in a type the caller is excluded from | 3 | 3 | 0 |
| referring record removed out of band (row gone, ref rows left) | 1 | 0 | 0 |

The first is a straight disagreement — the badge counts `DISTINCT record_id`, the panel
counts `(record_id, field_key)` pairs. The second is the documented-intentional one, and it
is the misleading shape the brief asked about: the editor reads "Referenced by 3" and the
panel says nothing references it. The third only follows an out-of-band delete
(`purge_type_records`/`hard_delete_record` do call `delete_index`, verified by
`::test_purged_referrer_leaves_no_index_rows`).

### m3. The referrers panel 404s for a trashed record whose badge the editor just rendered

*Probe:* `test_referrers_probe.py::test_the_panel_404s_for_a_trashed_record_whose_badge_the_editor_shows`

```
GET /admin/records/author/{uuid}  (trashed record, editor)  -> 200 props.referrer_count = 1
GET /api/records/types/author/records/{uuid}/referrers      -> 404
    {"detail":"no author record with uuid 'eda0…'"}
```

`views.record_edit` falls back to `get_deleted_record` for an editor, but
`endpoints/api/referrers.py:61` uses `record_service.get_record`, which does not — so the
panel behind the badge cannot be opened on exactly the screen (trash restore) where
"what still points at this?" matters most.

### m4. The public filter/sort grammar reaches the audit columns the public *shape* removes

*Probe:* `test_crosscut_probe.py::test_public_grammar_exposes_columns_the_public_shape_removes`

```
public shape: {"uuid","slug","display_title","published_at","data"}          # no audit columns
GET /api/records/public/article?sort=-updated_at                    -> 200
GET /api/records/public/article?filter=updated_at:gt:2020-01-01…    -> 200 total=1
GET /api/records/public/article?filter=updated_at:gt:2099-01-01…    -> 200 total=0
GET /api/records/public/article?filter=created_at:lt:2099-01-01…    -> 200 total=1
GET /api/records/public/article?filter=position:eq:0                -> 200 total=1
```

`contracts/public.py`'s docstring: "no audit columns, no `version`, no `status`". They are
removed from the response and left in the grammar (`index/_fixed.py:FIXED_COLUMNS`), so an
anonymous caller binary-searches `created_at`/`updated_at` to arbitrary precision and reads
the internal `position` ordering. Nothing private is reachable this way (the rows are all
published), but it contradicts the stated shape rule, and it is the one place the public
surface answers a question about a column it deliberately withholds.

### m5. `providers.register` validates nothing about a virtual key

*Probe:* `test_providers_probe.py::test_register_accepts_keys_it_should_refuse`,
`::test_a_virtual_field_shadowed_by_a_fixed_column_is_silently_dead`

```
registered VirtualField('status')     -> accepted
registered VirtualField('_orphaned')  -> accepted
registered VirtualField('')           -> accepted
registered VirtualField('Not A Key')  -> accepted
registered VirtualField('x'*300)      -> accepted
registered VirtualField('id')         -> accepted

rows the provider wrote: [('name','P'), ('status','bucket-a')]
filter status:eq:bucket-a -> QueryError: unknown status 'bucket-a'
```

`register` (`providers.py:217`) checks only "is this key already owned by another
provider". A key in `FIXED_COLUMNS` or in `RESERVED_FIELD_KEYS` is accepted, its rows are
written on every save, and `query._term` resolves the fixed column first — so the rows are
dead weight that nothing can ever read, discovered only by the host's own confusion. The
same set that `validate_key` refuses *declared* keys from should refuse *virtual* ones, and
`TYPE_KEY_PATTERN`/`MAX_KEY_LEN` should apply to both. (Refusing them would also have to
be reconciled with B1's direction of fix.)

### m6. A provider that writes a kind other than the one its `VirtualField` declares produces silent wrong answers

*Probe:* `test_providers_probe.py::test_a_provider_whose_kind_disagrees_with_its_virtual_field`

```
VirtualField("price_bucket", NUMBER) + IndexEntry(kind=TEXT, key="price_bucket", value="100")
rows written: text 2, number 0
filter price_bucket:is_null:true  -> [record]      # "it has no value", and a row exists
filter price_bucket:eq:100        -> []            # never matches
filter price_bucket:eq:not-a-num  -> QueryError bad_value
```

Nothing cross-checks `IndexEntry.kind` against the declared `VirtualField.kind` at write
time (`writer.row_values` writes whatever the entry says; `query._resolve` reads whatever
the registry says). §7.7's whole argument is that index bugs produce *wrong results, not
slow ones* — a one-line assertion in `writer.project` would turn this into a log line.

### m7. Provider-written `REF` rows silently gain delete-veto power and appear as referrers

*Probe:* `test_providers_probe.py::test_a_provider_ref_row_fabricates_a_referrer_and_blocks_a_delete`

```
IndexEntry(kind=REF, key="haunt", value=(author_uuid, 99999))   # 99999 is not a type id
ref rows: [('haunt', '9d92…', 99999)]

GET    …/records/{author}/referrers -> 200 {"items":[{"type_key":"note","display_title":"unrelated",
       "field_key":"haunt","field_label":"haunt","on_delete":"restrict","is_deleted":false}],"total":1}
DELETE …/records/{author}           -> 409 {"detail":"1 record(s) still reference 9d92…",
                                            "referrers":["e0be…"]}
```

`_relations.referrers` reads `records_index_ref` without checking that `field_key` names a
relation field of the referring type or that `target_type_id` exists; `_on_delete` falls
back to `restrict` for an unknown key. So a provider — the documented extension point for
*computed* index rows — can make arbitrary records undeletable and put fabricated rows in
the delete dialog. Host code is trusted, but §7.6 sells providers as additive projection,
not as participation in referential integrity; the README's "Extending the index" section
should at minimum say REF entries are load-bearing.

---

## NOTES

* **n1.** `on_startup` is not idempotent: running it twice appends a second identical
  `PublicRoute` to the registry (`test_boot_probe.py::test_on_startup_twice_duplicates_the_exemption`).
  Harmless today (matching is `any(...)`, and the router mount is de-duplicated by path),
  but it is the kind of thing a host that restarts the lifespan in-process will grow.
* **n2.** Declaring `GET` and `HEAD` on one `api_route` gives both operations the same
  `operationId`; FastAPI warns twice per route when the schema is built (`UserWarning:
  Duplicate Operation ID list_public_records_api_records_public__type_key__get`). Cosmetic,
  but it breaks generated clients for the public API.
* **n3.** `providers` module-global state (`_providers`, `_virtual`, `_owners`, `_shadowed`)
  is mutated without a lock and read on every write and every query. Declared out of scope
  by the brief; noting once. `clear()` at runtime leaves the rows in the tables and turns a
  working filter into `400 unknown`
  (`test_providers_probe.py::test_clear_mid_process_turns_a_working_filter_into_a_400`).
* **n4.** `expand` is not refused while a relation field is mid-reindex — a filter on it is
  409, an `?expand=` of it is 200
  (`test_expand_probe.py::test_expand_on_the_trash_and_on_a_reindexing_field`). Correct as
  far as I can tell (expansion reads the payload, not the index), just undocumented.
* **n5.** `role_blocked(rtype, None)` vs `role_blocked(rtype, [])` is a real and load-bearing
  distinction (`test_extras_probe.py::test_expand_with_no_caller_resolves_everything`):
  `deps.caller_roles` returns `[]` for an anonymous request, so a narrowed type is redacted
  rather than resolved. Correct, and worth a test in the module's own suite.

---

## Held up

Everything below was probed and behaves as §9/§10/§15/§16 say it should.

**Public read API** — a private type is a byte-identical `404 {"detail":"not found"}` by key,
by uuid and against a nonexistent type; drafts, trashed rows and unknown uuids likewise, and
the list `total` is 0 for them (`test_public_probe.py::test_private_type_by_key_and_uuid_is_identical_to_missing`,
`::test_draft_and_trashed_records_are_404`). `page_size=100000` clamps to 200 and `page=0`,
`page=-1`, `page_size=0` are 422 (`::test_paging_edges`). `HEAD` answers 200/404 on both
routes with an empty body, `POST` is 405 (`::test_head_on_both_routes`). `expand`,
`trashed` and `include_deleted` arrive as unknown params and are ignored, with no
`expanded` key and no leak of the private target's title
(`::test_unknown_params_are_ignored`). A field in `reindex_pending` is
`400 {"detail":"cannot filter or sort by 'title'"}` with no `reason`/`field` and no mention
of reindexing, while the admin API answers 409 for the same field
(`::test_reindexing_field_is_400_without_the_marker`). `longtext`/`json`/`media` are refused
`indexed: true` at schema save and are 400 as filters; `unique` normalises to `indexed`
(`schema/fields.py:_validate_flags`), so "unique but not indexed" is unrepresentable
(`::test_unindexable_types_refuse_indexed_and_filters`). `allowed_roles` on a public type is
correctly irrelevant to the anonymous read (`::test_allowed_roles_do_not_narrow_the_anonymous_read`).
Traversal and case variants reach no admin route — `%2e%2e`, `..%2f`, `//` and `/API/…` all
404, and a client-normalised `../` becomes an ordinary admin request that 401s
(`::test_traversal_and_case_variants_do_not_reach_admin_routes`). The default prefix exempts
only `GET`/`HEAD` under `/api/records/public/` and no admin or view path
(`test_boot_probe.py::test_default_prefix_exempts_only_the_public_surface`). `is_public`
toggled off takes effect on the very next request, no restart
(`test_extras_probe.py::test_is_public_toggle_takes_effect_on_the_next_request`). Filtered
public totals count published rows only (`::test_public_total_counts_only_published_under_a_filter`),
and malformed filters/sorts are all 400 (`::test_malformed_public_filters`).

**`?expand=`** — depth 2 is unreachable (`expand=book.author` → 400) and an `ExpandedRef`
carries no `data` (`test_expand_probe.py::test_depth_two_is_not_reachable`). `restricted`
wins over `dangling` when both hold (`::test_dangling_and_restricted_together`). Empty,
whitespace-only, and 100× repeated keys are all one 200 with one query; a fixed column
(`status`, `display_title`), `_orphaned`, a non-relation field and an unknown key are each a
400 naming the key and the reason (`::test_expand_key_edge_cases`). `?trashed=true&expand=`
works and resolves live targets (`::test_expand_on_the_trash_and_on_a_reindexing_field`).
Statement count for a 200-record page with 5 relation fields is exactly
`1 (type) + 1 (count) + 1 (page) + 1 (target types) + 5 (one per field) = 9`, no per-row
queries (`::test_statement_count_for_a_page_of_200_with_five_relation_fields`). Duplicated
uuids in a to-many field are expanded once and rendered in payload order.

**Referrers** — `total` counts redacted referrers and `items` omits them
(`test_referrers_probe.py::test_total_counts_what_items_redacts`); self-references are
dropped from both the list and the badge (`::test_self_reference_is_dropped_from_both`);
trashed referrers are listed with `is_deleted: true` and still do not block a `restrict`
delete, matching Phase 1 (`::test_trashed_referrer_is_marked_and_still_does_not_block_a_delete`);
purging a record through the module removes every one of its index rows, so no ghost
referrers survive (`::test_purged_referrer_leaves_no_index_rows`); paging edges are 422 for
`page=0`/`page_size=0` and an empty page past the end
(`::test_referrers_paging_edges`). `delete_type` refuses while another type's relation
targets it, so "referrer in a deleted type" is not reachable (`services/types.py:150-165`).

**Extension point** — a second provider claiming a registered key is a `ValueError` naming
the owner, and the first provider survives (`test_providers_probe.py::test_double_registration_of_one_key_is_a_value_error`).

**Cross-cutting** — the three revision routes survived the `records.py` → `revisions.py`
split with identical verbs, paths and router prefix, nothing lost or gained
(`test_crosscut_probe.py::test_the_revision_routes_survived_the_split_unchanged`); every API
router including the new `public`/`referrers` carries `route_class=RecordsErrorRoute`
(`::test_every_api_router_uses_the_error_route`); `FieldSchemaError` is still importable
from `schema.fields` after the `_keys.py` split and the three reservation messages are
unchanged (`::test_field_schema_error_is_still_importable_from_fields`); the full route
table is as designed (`::test_full_route_table`). The only `select(func.count(...))` the
three commits add is `_relations.referrer_count`, whose soft-delete-bypass is deliberate and
documented (consequences in m2); the commits add no Core DML, so no missing `mark_written`.

---

## Totals

| severity | count |
|---|---|
| blocker | 1 |
| major | 4 |
| minor | 7 |
| note | 5 |

55 probes across 8 files, all passing (each asserts observed behaviour).
