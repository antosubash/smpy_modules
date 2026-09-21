# Records — administrator's guide

This guide walks the admin screens in the order you meet them. It uses the
exact labels the UI shows. If you are calling the module over HTTP instead,
read [api-reference.md](api-reference.md); if you are installing or running it,
read [operations.md](operations.md).

Three permissions gate everything here:

| Permission | Lets you |
|---|---|
| `records.view` | See types and read their records |
| `records.edit` | Create, change, trash, restore and purge records; see the Trash; import |
| `records.manage_types` | Create and change Record Types, preview and apply schema changes, delete a type |

A type can narrow these further with **Allowed roles** — see
[Allowed roles](#allowed-roles).

---

## 1. Finding your way in

### The sidebar

The admin sidebar has a **Records** entry under the **Content** group. It opens
the Records hub at `/admin/records/`.

If a type has **Show in sidebar** turned on, it also gets an entry of its own,
in a separate **Records** group directly below Content, labeled with the type's
plural and using the type's icon. That entry links straight to the type's record
list. This is off by default: an install with thirty types would have an
unusable sidebar.

> A per-type entry can lag behind by a few seconds on a host running several
> worker processes. The worker that served your save updates immediately;
> others notice within `menu_refresh_seconds` (5 by default). Nothing about the
> records is affected — only which links the sidebar shows.

### The Records hub

`/admin/records/` is headed **Records**, with the subtitle *"Every record type
in this install."* Each type is a row showing its icon, label, description and
**{n} records** (plus **({n} trashed)** when the Trash is not empty), and a
badge **In sidebar** when that is on.

Two actions per row:

- clicking the label opens that type's **record list**;
- **Edit schema** opens the type editor.

**New type** creates one. Once you have more than a dozen types, a **Filter
types** box appears with the placeholder *"Filter by name or key…"*; it matches
on name or key and says *"No record type matches "x"."* when nothing does.

A type you are excluded from by its **Allowed roles** is not listed at all —
not listed and then refused when you open it.

---

## 2. Creating a Record Type

**New type** opens a form in three sections: **Details**, **Fields** and
**Record identity**.

### Details

| Control | What it is |
|---|---|
| **Key** | The type's permanent identifier — `blog_post`. Lowercase letters, numbers and underscores, starting with a letter, at most 64 characters. **Chosen once; this can't be changed later.** |
| **Label** | The singular name shown in the UI. Typing it auto-fills Key and Plural label. |
| **Plural label** | Used for the record list heading and the sidebar entry. |
| **Description** | Free text, shown on the hub row. |
| **Icon** | One of the framework's navigation icons (`database` is the default). Not every lucide-react name works — see the warning below. |

The Key field refuses, inline: a missing key (*"A key is required."*), a
reserved one (*""status" is reserved by the module."*), a bad shape (*"Must
start with a lowercase letter, and contain only lowercase letters, numbers and
underscores."*) and a duplicate (*"Another type already uses this key."*).
`types` and `new` are reserved because they would shadow the editor's own URLs.

> **An icon name the framework does not know renders nothing at all.** The
> picker's help lists examples; a valid lucide name that is not on the
> framework's allowlist (`flask-conical`, for instance) silently draws an empty
> space on the hub row and in the sidebar. The editor shows *""{name}" is not
> one of the framework's navigation icons…"* when it can tell.

### Fields

**Add field** appends a row. Each row collapses to `key · type · badges` and
expands when you click it. **Move up** / **Move down** reorder; the arrows keep
keyboard focus on the row that moved. **Remove field** deletes it — on a type
that already holds records, that is a *destructive* change; see
[section 6](#6-changing-a-schema-that-already-holds-records).

Every field has:

| Control | Meaning |
|---|---|
| **Key** | The payload key. Same rules as a type key. *"Can't be changed after the field is created."* There is no rename: a rename is a remove plus an add, and it blanks the column. |
| **Type** | One of the fourteen kinds below. |
| **Help text** | Shown under the input on the record editor. |
| **Required** | The record cannot be saved without a value. On `text`, `longtext`, `email`, `url` and `select`, `""` and whitespace do **not** satisfy it. |
| **Unique** | No two records of the type may hold the same value. Implies Indexed. |
| **Indexed** | *"The single most consequential choice on this screen: filterable and sortable, at the cost of a write per save."* |
| **Default value** | Used when a record is created without one. Validated against the field's own rules at save time. |

#### What "Indexed" buys, and what it costs

**If a field is not indexed, it is not queryable.** No endpoint and no screen
filters, sorts, searches or groups by a field that is not indexed. The record
payload is opaque storage; every query runs against a separate typed index
table. This is a hard rule, not a limitation to be lifted later — it is what
keeps performance a property of the schema rather than a cliff you find under
load.

Indexing a field means:

- it can be a filter and a sort key on the record list, the export, the
  aggregate endpoint and the public API;
- it can be one of the record list's columns (the first four indexed fields
  other than the display field become columns);
- every save writes one extra index row per value. A type with 80 indexed
  fields turns one save into 81 inserts, which is why there is a ceiling of 25
  indexed fields per type (and 100 fields in total).

Three kinds cannot be indexed at all: `longtext`, `json` and `media`. The editor
refuses `Indexed` on them.

A `relation` field is **always** indexed whatever the checkbox says: `on_delete`
is enforced by asking the index who points at a record, so an unindexed relation
would accept `restrict` and enforce nothing. It counts against the ceiling.

#### The field kinds

| Type | Stores | Indexed as | Options | Constraints |
|---|---|---|---|---|
| `text` | A single line | text | — | Minimum length, Maximum length, Pattern (regex) |
| `longtext` | Multi-line prose | *not indexable* | — | Minimum length, Maximum length, Pattern (regex) |
| `number` | A decimal, **five decimal places** | number | — | Minimum, Maximum |
| `integer` | A whole number | number | — | Minimum, Maximum |
| `boolean` | True/False | bool | — | — |
| `date` | A calendar date (`YYYY-MM-DD`) | date | — | — |
| `datetime` | An instant | datetime | — | — |
| `select` | One of a fixed list | text | **Choices** | — |
| `multiselect` | Several of a fixed list | text (one row per value) | **Choices** | — |
| `email` | An email address | text | — | Minimum length, Maximum length, Pattern (regex) |
| `url` | An `http(s)` URL with a host | text | — | Minimum length, Maximum length, Pattern (regex) |
| `json` | Any JSON object or array | *not indexable* | — | — |
| `media` | A media reference | *not indexable* | — | — |
| `relation` | A link to another record | ref | **Target type**, **Many**, **When the target is deleted** | — |

**Choices** (on `select` and `multiselect`) are a list of value/label pairs.
Values must be unique and non-empty. The editor shows **{n} choices** with
**Show**/**Hide**, and a **Paste a list** bulk-entry box: one per line,
separating stored value from label with `|` or `=`; a line with neither is used
as both.

**Relation options:**

- **Target type** — which Record Type this points at. A picker of existing
  types (*"Choose a type…"*).
- **Many (a list of records)** — off means one reference, on means a list.
  `Unique` is meaningless on a to-many relation and is refused.
- **When the target is deleted** — the `on_delete` rule:
  - **Restrict (block the delete)** — the default. Deleting the target is
    refused while this record points at it.
  - **Set null** — the reference is cleared.
  - **Cascade (delete this record too)** — this record is trashed with the
    target.

  `restrict` is the default deliberately: a cascade default across a graph an
  administrator defined deletes content nobody asked to delete.

**A `number` is stored with five decimal places.** A value the index would round
is refused on write rather than stored with payload and index disagreeing. That
contract is exact on PostgreSQL; on SQLite, which has no decimal type, it is
approximate. If you need more precision, use `text` or `json`.

**Some field keys are reserved** because a record row already has a column of
that name: `_orphaned`, `id`, `uuid`, `type_id`, `data`, `schema_version`,
`version`, `status`, `slug`, `locale`, `translation_group`, `display_title`,
`position`, `published_at`, `created_at`, `updated_at`, `created_by`,
`updated_by`, `is_deleted`, `deleted_at`, `deleted_by`. The editor refuses them
with *""{key}" is reserved by the module: it names a column every record already
has."*

### Record identity

Two pointers, both selects over the type's own fields, both offering **None**
and both disabled with *"Add a field first."* until there is one.

- **Display field** — *"The field a record is listed and linked by — its title
  in every list."* It must point at a `text`, `select`, `email`, `url`,
  `integer`, `number`, `date` or `datetime` field. Changing it recomputes every
  record's title (an index-affecting change).
- **Slug field** — the field a new record's address is derived from. Must be a
  `text`, `select`, `email` or `url` field. **Changing it never regenerates
  existing slugs** — a slug is an address, and regenerating one could break a
  link or collide with a slug handed out since. Only records written after the
  change use the new pointer.

### The flags

| Flag | What it does |
|---|---|
| **Public** | *"Exposes a read-only public API for this type's published records."* Anonymous callers can list and read the type's published records. The editor shows the URL with a **Copy** button and the note *"Published records only, filterable only on indexed fields, and never expanded."* Off by default. See [api-reference.md § Public read API](api-reference.md#public-read-api). |
| **Translatable** | *"Records can exist in several languages ({locales}); each translation is its own record with its own slug."* Only meaningful when the install is configured with more than one content language. |
| **Show in sidebar** | Adds the type's own entry to the admin sidebar. Off by default. Not a schema change: no classification, no dry run, no revision. |
| **Allowed roles** | Narrows who may use this type's records. See below. |
| **Collection** | Which table set holds this type's records. **Chosen once** — *"A type can't be moved between collections once it is created."* The default is **Shared tables**. Only collections the host declared in code appear here. |

Turning **Translatable** *off* while records exist in another language is
refused with a count: those records would stay in the database, keep their slug
claims, and be unreachable from a UI that no longer offers their language.

### Allowed roles

*"Leave empty so anyone who can view or edit records can work with this type's
records. Selecting roles narrows viewing and editing of its records to those
roles; managing the type itself is never narrowed."*

Empty — the default — means every caller holding the static permission may work
with the type. A non-empty list narrows it, **with no admin bypass**: a caller
holding the `admin` wildcard is refused unless `admin` is one of the listed
roles. So if you restrict a type to a role you do not hold, you lock yourself
out of its records and have to use `records.manage_types` to widen the list
again.

The narrowing applies to reads exactly as it does to writes. A caller the list
excludes gets a 403 on the record list, on individual records, on their
referrers and revisions, and on the admin screens over them — and the type is
omitted from the hub and from `GET /api/records/types` entirely, rather than
listed as a card that fails when opened.

One exception: a **`records.manage_types`** holder can always open the type
editor and read the type's definition, whatever Allowed roles says. A manager
locked out of the screen that edits Allowed roles would be a one-way door.

> **Two honest limitations.** Per-type Allowed roles are invisible in the
> framework's role editor: an administrator editing roles sees only the three
> coarse permissions and has no way to discover from that screen that a type is
> further restricted. And a schema **preview** (below) lists up to ten failing
> records by title, and is gated on `records.manage_types` rather than on the
> type's Allowed roles — so Allowed roles hides titles from the record API, not
> from a schema preview.

### Danger zone

At the bottom of an existing type's editor. **Delete this type** *"Deletes this
type and every record stored against it, including the trash. This cannot be
undone."* The confirmation dialog says *"This permanently deletes "{label}" and
its {n} record(s) (live and trashed). Type {n} to confirm."* and refuses a
mismatch with *"That doesn't match. Type the exact number to confirm."*

If another type has a relation field pointing at this one, the editor says so
first: *"Other types still have a relation field pointing at this one:"*.

---

## 3. The record list

`/admin/records/{key}` — headed with the type's plural label.

### Columns

In order: **Title** (the display field), **Status**, **Language** (only when the
type is **Translatable** *and* the install runs more than one content
language), then up to **four** indexed fields
in the type's own field order (the display field is not repeated), then
**Position** (only when at least one record on the page has a non-zero
position), **Published on**, **Updated** and **Actions**.

A relation column renders the target's title; a to-many relation renders the
titles comma-separated. A boolean renders as a check or a dash. `select` and
`multiselect` render through their configured labels.

At phone width the table is replaced by one card per record, with the same
fields as meta lines and the row action visible.

Clicking a column header cycles its sort: none → ascending → descending → none.
Clicking a different column starts it ascending. The UI keeps one sort key; the
URL grammar allows several.

### Filtering

The filter bar has three controls — **Field**, **Condition** and **Value** —
plus **Apply** and **Clear**. Pressing Enter in the Value box applies. The
filter is written into the URL as `?filter=field:op:value`, so a filtered list
is a link you can share; Back undoes it.

**Field** offers the indexed fields of the type plus the fixed columns every
record has. Where a declared field's label collides with a fixed column, the
option shows the key in brackets — *Status (order_status)* against
*Status (status)*.

**Condition** offers only the operators that mean something for that field's
kind:

| Field kind | Conditions offered |
|---|---|
| `text`, `longtext`*, `select`, `multiselect`, `email`, `url` | **is**, **is not**, **contains**, **starts with**, **is empty** |
| `number`, `integer`, `date`, `datetime` | **is**, **is not**, **>**, **>=**, **<**, **<=**, **is empty** |
| `boolean` | **is**, **is not**, **is empty** |
| `relation` | **is**, **is not**, **is empty** |

\* only if it were indexable, which it is not — it never appears in the picker.

The URL grammar additionally accepts **is one of (comma-separated)**
(`in:a,b,c`), which the bar does not offer.

Two operators are worth knowing:

- **starts with** is case- and collation-sensitive, and cheap: it is answered
  from the index by seeking.
- **contains** is case-insensitive and forgiving, and expensive: it scans.

On a **multiselect** or a to-many **relation**, **is** matches a record holding
*any* of the values, and **is not** matches one holding *none* of them.

If a filter cannot be applied the list renders empty with the reason inline:

| Notice | Means |
|---|---|
| *"That field doesn't exist on this record type."* | The field was renamed or removed |
| *"That field isn't indexed, so it can't be filtered or sorted on."* | Turn on Indexed and wait for the rebuild |
| *"That condition isn't supported for this field."* | e.g. `>` on a text field |
| *"That value isn't valid for this field."* | e.g. a non-numeric value for a number field |
| *"That field is being reindexed right now and cannot be filtered on yet. Try again shortly."* | A schema change is still rebuilding — temporary |
| *"That filter couldn't be applied."* | The term did not parse |

An empty result says *"No records match this filter."* with a **Clear** button
inside the box. A type that genuinely has no records says *"No records yet"*
with a **New record** button. The Trash, when empty, says *"No trashed
records"*.

### Paging

The footer reads **Showing 1–25 of 180** and **Page 1 of 8**, with **First**,
**Previous**, **Next**, **Last** and a **Per page** select offering 25/50/100.
Every one of them writes into the URL, so Back walks back through them.

On a large type the count stops at 10,000: the footer then reads **Showing
1–25 of 10,000+** with the explanation *"More than 10,000 records match; the
count stops at 10,000."* That ceiling is the `max_count` setting.

### Trash

**Trash** switches the list to the type's soft-deleted records; **Back to live
records** switches back. Listing the Trash needs `records.edit`, not merely
`records.view` — enumerating it is how anything gets restored.

What the Trash keeps, and why it matters:

- **A trashed record keeps its slug claim.** Creating a new record whose slug
  would collide with a trashed one is refused until the trashed one is restored
  or permanently deleted.
- **A trashed record keeps its `unique` claims.** A duplicate value is refused
  with *"A record with this value already exists — it may be in the Trash, which
  keeps its claim until it is deleted permanently."*
- **A trashed record still shows up as a referrer** (flagged **Trashed**), but
  it no longer blocks a delete.
- **A trashed record is never served to the public API** and is never counted
  in an aggregate.

To clear a claim, open the trashed record and use **Delete permanently**
(*"This cannot be undone. Delete this record permanently?"*). **Restore** puts
it back (*"Restore this record?"*).

### Export

The **Export** button is a menu (it carries a chevron) with **Download JSON**
and **Download CSV**.

1. Set up the list you want first — the export takes the *current*
   `filter` and `sort` from the URL. A filter the list refuses is refused before
   any download starts.
2. Pick a format. The file is named `<key>-<date>.json` or `.csv`.

Exporting while the Trash is showing exports the trashed records, and the menu
warns: *"A trash export can't be re-imported — restore or purge the records
first."*

The export streams, so a large type does not have to fit in memory.

### Import

**Import** opens a file picker, then a dialog headed **Import preview** showing
the file name and the options in force, e.g.

> `contacts.csv — Create or update (upsert) · match by Record ID (uuid) ·
> overwrite unversioned rows: off`

Nothing is written yet: the dialog shows a **dry run**. The summary reads
*"{total} row(s): {created} to create, {updated} to update, {skipped} unchanged,
{failed} failed"*, followed by any row errors as *"Row {n} ({field}):
{message}"*. Changing an option re-runs the dry run.

**Import options:**

| Option | Values | Meaning |
|---|---|---|
| **Mode** | **Create or update (upsert)** (default), **Create only**, **Update only** | Whether a matched row may be updated, and whether an unmatched row may be created |
| **If a row fails** | **Stop and write nothing** (default), **Skip it and write the rest** | All-or-nothing, or partial |
| **Match existing records by** | **Record ID (uuid)** (default), **Slug**, or the key of a `unique` field | How a row finds the record it updates |
| **Overwrite unversioned rows** | off (default) / on | *"Overwrite records whose version the file does not carry."* An export deliberately carries no version, so updating from one needs this |

Notes:

- Matching by **Slug** slugifies the cell first, so `Hello World` matches the
  record whose slug is `hello-world`.
- Matching on a field that is not `unique` is refused outright rather than
  resolved arbitrarily.
- Rows the record already agrees with are **skipped**, not written — which is
  why re-importing an export is a no-op and versions do not move.
- Failed rows that were refused only for a missing version get the hint *"These
  rows were refused because the file carries no version for a record that
  already exists — turn on "Overwrite unversioned rows" above and import
  again."*
- The report lists row numbers, not titles: *"This report lists row numbers, not
  record titles — showing titles here would need the import endpoint to return
  them."*

**Apply import** writes it. The dialog switches to **Import result** with the
past-tense summary. No toast fires — the result is on screen.

A file that is neither JSON nor CSV is refused with *"Couldn't tell whether that
file is JSON or CSV — save it with a .json or .csv extension and try again."*;
malformed JSON with *"That file isn't valid JSON — open it in a text editor and
check it's complete."*

The exact file formats are in
[api-reference.md § Import and export formats](api-reference.md#import-and-export-formats).

---

## 4. The record editor

**New record** opens `/admin/records/{key}/new`; clicking a row opens
`/admin/records/{key}/{uuid}`. Creating a record lands you on its editor with a
**Record created** toast.

### The envelope

The header carries the controls that are about the record rather than its
content:

- **Status** — **Draft** or **Published**. Publishing stamps `published_at` the
  first time; unpublishing and republishing keeps the original stamp.
- **Language** — shown only when the type is Translatable and the install runs
  more than one content language, as a badge with the help *"This record's language is fixed for its
  lifetime."* It is chosen at creation and can never be changed. See
  [section 5](#5-languages-and-translations).

Under **Advanced**, hidden until you open it:

- **Slug** — *"The address this record gets in a public URL."* Leave it blank
  and it is derived from the type's slug field (*"Leave blank to derive it from
  {field}."*). Slugs are unique per type and per language; a taken slug is
  refused.
- **Position** — *"Orders this record in a public list. Leave it at 0 to sort by
  date."*

### The fields

Below the envelope, under **Fields**, one input per declared field in
declaration order, with its help text. Required fields are marked **Required**.
A `select` shows **— choose —** until picked; a `multiselect` shows *"This field
has no choices yet."* when the type declares none. A field kind the current
version cannot render says *"This field type ({type}) is not editable in this
version."*

**Advanced: edit raw JSON** switches to a textarea holding the whole payload
(*"Raw JSON for this record's fields. Switching back re-fills the form from
it."*); **Back to the form** switches back. Invalid JSON is flagged **Invalid
JSON**.

A type with no fields yet says *"This type has no fields yet. Add some on its
schema screen."*

### What an error looks like

**Save** either succeeds with a **Saved** toast, or fails and:

1. scrolls back to the top of the form,
2. announces *"{n} fields need attention"* in a live region,
3. focuses the first offending input,
4. marks each bad field inline.

The inline message clears as you type. The messages are specific — *"This field
is required"*, *"Must be at least {min} characters"*, *"Not a valid email
address"*, *"Must be an http:// or https:// URL with a host"*, *"At most 5
decimal places are stored"*, *"Not one of the configured choices"*, *"Not valid
JSON"*, *"Must be a JSON object or array, not a scalar"*, *"Not a valid link to
a record"*.

Leaving with unsaved changes asks *"You have unsaved changes. Leave this page
and lose them?"*

If the connection drops you get *"Couldn't reach the server. Your changes are
still on this page; try again."* and your typing survives. If your session has
expired: *"Your session has expired. Taking you to the sign-in page — your
changes are still on this page until you leave it."*

### Relations and the picker

A relation field renders as a search box — *"Search by title…"* — that behaves
as a combobox: type to search, arrow keys to move, Enter to pick, Escape to
close, and a live region announcing *"{n} records found"*. No match says *"No
matching records"*. A to-many field shows the picks as chips, each with a
**Remove** button.

A reference whose target is gone shows **Missing record**; one whose target is
in the Trash shows **Deleted** with the tooltip *"The record this pointed at has
been deleted."*; one whose target's type excludes you shows **Restricted**. A
relation field whose type has no target configured says *"This relation field
has no target type configured."*

Relations are always resolved on this screen — a picker showing raw UUIDs is not
an editor.

### Referenced by

A panel headed **Referenced by {n} records** with **Show**/**Hide**. Empty, it
says *"Nothing references this record."* and carries no toggle.

Each entry names the referring record, the field it points from, the field's
label and its **Restrict** / **Set null** / **Cascade** behavior, with
**Trashed** on trashed referrers. **Load more** pages through them. If some
referrers belong to a type you cannot see, the panel says so rather than leaving
you to subtract: *"Some referrers are not visible to you."*

### Deleting a record

**Delete** first checks what points at this record (*"Checking what references
this record…"*), then shows a dialog that says what will happen:

- *"{n} records will block this delete"* — with *"Detach or change these
  references before deleting."* This is a `restrict` relation; the delete is
  refused until you change them.
- *"{n} records will have this reference cleared"* — a `set_null` relation.
- *"{n} records will be deleted too"* — a `cascade` relation.

Confirming says *"Move this record to the Trash? You can restore it until it is
deleted permanently."* and the toast reads **Moved to the Trash** with **View
trash** and **Undo**. Undo restores it (**Record restored**).

Deleting never touches a record's translations: a translation group is a
grouping, not a cascade.

### History

A panel headed **History** with **Show**/**Hide**, listing every earlier version
(*"No earlier versions yet."* when there is none). Each entry carries its
version, schema version, what happened (create/update/delete/restore), the title
at the time, when, and who.

**Restore this version** asks *"Restore the data from v{version}?"* and replays
that payload through the ordinary save path — so it is validated. A version that
no longer fits the type's current schema is refused: *"This version no longer
fits the type's current schema."*

How many versions are kept is the `revision_limit` setting (50 by default, per
record). The oldest beyond that are pruned on write.

### The conflict panel

If someone else saved the record while you had it open, Save answers with
**This record changed while you were editing** and the explanation *"Someone
else saved a change to this record since you opened it. Reload to see the latest
version, or overwrite it with what you have."* The panel shows **Current on the
server** beside **Your unsaved version**, and offers **Reload** or **Overwrite
anyway**.

The type editor has the same panel — **This type changed while you were
editing** — but only offers **Reload**, because a schema change has to be
reapplied deliberately.

### Records that no longer fit the schema

A record marked invalid by a forced schema change shows the badge **Outdated
schema** on the list and, in the editor, a panel headed **This record does not
satisfy the current schema** naming the fields. The record still holds its
values and is still editable; saving it validates against the current schema
like any other save.

**Fields changed since this was saved** is a different, milder notice: the type's
schema moved on since this record was last written, and the record will be
rewritten at the current schema version on its next save.

---

## 5. Languages and translations

Only relevant on an install configured with more than one content language (the
`content_locales` setting) and on a type with **Translatable** on.

### The rule

**A record's language is fixed for its lifetime.** There is no "change
language". A record in another language is a *whole sibling record* sharing a
`translation_group` — its own slug, its own status, its own payload.

### The Languages panel

On the record editor, headed **Languages**. It lists one row per configured
content language:

- the record you are on is marked **Editing**;
- a sibling that exists offers **Open**;
- a language with no sibling yet offers **Add translation** (**Creating…**
  while it runs);
- a trashed sibling is marked **Trashed** — and it still holds that language, so
  you cannot add another until it is restored or purged.

The new sibling copies the source's payload and position, starts as a **Draft**
whatever the source's status, and gets a slug regenerated in the target
language, suffixed `-2`, `-3`… if something there already holds it.

### What this buys, and what it costs

- **Slugs are unique per (type, language)**, so the same word can be the address
  in both languages.
- **The record list defaults to all languages** — an editor's question is "what
  exists", not "what exists in English". The **Language** column and a
  `locale` filter narrow it.
- **Deleting a record never touches its siblings.**
- **There is no per-field translation, no automatic translation, and no
  fallback**: a missing German sibling is a 404 for a German reader, not the
  English record in disguise.
- **`unique` is enforced among records that are *not* siblings.** A German
  product may legitimately carry the English product's SKU, so a translation may
  copy a unique value; two records in different translation groups collide as
  they always did.
- **Allowed roles, Public and `on_delete` are type-level and language-blind.**

---

## 6. Changing a schema that already holds records

Every change to a type's fields is diffed against the stored schema and
**classified** before anything is written. The class of a whole change is the
most severe class in it.

| Class | Shown as | What it is | What happens |
|---|---|---|---|
| Additive | **Additive** | A new optional field, a new choice, a relaxed constraint, a label or help edit | Applied immediately; records untouched |
| Index-affecting | **Rebuilds index** | Toggling Indexed, retyping an indexed field, re-pointing a relation or flipping Many, changing the display field | Applied immediately, then the index is rebuilt in the background. The field refuses filters and sorts until the rebuild finishes |
| Restrictive | **Restrictive** | A new required field, a narrowed type, a tightened constraint, a removed choice, a newly unique field | Refused unless every record passes — or you force it |
| Destructive | **Removes data** | Removing a field | The values are kept under a reserved key, not deleted |

The editor names each individual change: **Field added**, **Field removed**,
**Type changed**, **Made required**, **No longer required**, **Made unique**,
**No longer unique**, **Indexing turned on**, **Indexing turned off**,
**Constraint tightened**, **Constraint relaxed**, **Choice added**, **Choice
removed**, **Options changed**, **Label changed**, and **Display title field
changed — every record's title will be recomputed**.

A live-record notice sits above: *"{n} live, {trashed} trashed records — changes
are checked against them before they apply."*

### Preview changes

**Preview changes** runs a dry run over every record of the type, the Trash
included, and writes nothing. It reports *"{checked} records checked, {failing}
would fail"* and, when something fails, **This change would leave records
invalid** with up to ten failing records named by title.

On a large type the preview runs as a background job instead of inside the
request: the button shows **Checking…** and then **Checked {n} of {m}…** until
it finishes. If the report is no longer available the editor says *"The preview
expired; preview again."* or *"The check could not be completed. Try previewing
again."* with a **Preview again** button. Previewing again writes nothing, so it
is always safe.

The threshold is the `preview_sync_limit` setting (5,000 records by default).

### Check records

**Check records** sits next to Preview changes. *""Check records" runs the same
dry run against the schema exactly as it is saved. Neither button writes
anything."* It answers with **Records checked against the saved schema**.

**Its one limitation is stated on screen.** If nothing has changed since the
schema was saved, the server does not re-scan: *"Nothing has changed since this
schema was saved, so the server did not re-scan these {n} records — it runs the
check only for a change that could break something."* That is an honest "we did
not look", not a clean bill of health. To actually re-validate every record
against the current schema, make a change that could break something (or preview
one) — or export the type and re-import it as a dry run.

### Refusal, and forcing

A restrictive change that would leave records invalid is **refused** with the
report. You then have three options:

1. change the proposal so every record passes — most often by giving the new
   required field a **Default value**;
2. fix the records first;
3. **Apply anyway**.

**Apply anyway — {n} records will be marked invalid** asks *"Apply this change
anyway?"* / *"{n} record(s) will be marked as not satisfying the schema, rather
than being changed or deleted."* The failing records are **marked, not
rewritten**: they keep every value, stay editable, and read back with the fields
that no longer fit.

### The last-applied report

After a forced apply, the editor keeps a panel: **Last applied change left {n}
records invalid**, with *"They still hold their values and are still editable —
opening one shows what no longer fits. This list is a sample of {shown} and is
lost when you leave this page."* Each sample entry links to its record, and
**Copy record IDs** puts them on the clipboard.

> **Copy that list before you navigate away.** It is not stored anywhere. The
> record list has no "invalid" badge and no "invalid" filter, so once the panel
> is gone the only way to find the marked records again is to open them.

### Removing a field, and putting it back

Removing a field is **destructive** but not lossy: each record keeps the value
under a reserved `_orphaned` key, moved there on that record's next write.

Re-adding a field with the same key is refused while orphaned values exist, and
the editor asks which you want under **These fields still hold values from a
previous delete** / *"Restore brings those values back into the field; discard
drops them for good."*:

- **Restore** — the old values come back and are re-indexed.
- **Discard** — they are dropped. This is the one bulk rewrite the module ever
  does, and it touches only that sub-key. It needs the type's Allowed roles on
  top of `records.manage_types`.

The conflict is reported per key: *"{key}: {n} records still hold a removed
value"*.

### Reindex pending

An index-affecting change enqueues a rebuild, and the editor shows **Rebuilding
the index for:** with each pending field (or **Whole type**) and **since
{time}**. While an entry is listed, that field cannot be filtered or sorted on
— the list says *"That field is being reindexed right now and cannot be filtered
on yet. Try again shortly."*

**Reindex now** (**Scheduling…**) re-runs it. If a worker restarted mid-rebuild
the entry can get stuck; `/health/ready` degrades after
`reindex_stale_after_seconds` (15 minutes) and an operator can finish it from
the command line — see
[operations.md § Reindexing](operations.md#reindexing).

> **A stuck rebuild on a `unique` field refuses every write to the type**, not
> just filters, because the uniqueness check is a query over the index. The
> health detail says so.

### Schema history

A panel headed **Schema history** with **Show**/**Hide**, listing each version
as **v{n}** / **schema v{n}** / **{n} fields**. **Restore this schema** asks
*"Restore the schema from v{version}? This is checked the same way any other
schema change is."* — so a rollback that would leave records invalid is refused
exactly like any other change, and can be forced exactly the same way.

Field keys are immutable throughout: a "rename" is a remove plus an add, and is
classified as both.

---

## 7. Where to go next

- The same operations over HTTP, with the exact wire shapes:
  [api-reference.md](api-reference.md)
- Settings, the CLI, health checks and deployment constraints:
  [operations.md](operations.md)
- What it costs at scale: [performance.md](performance.md)
