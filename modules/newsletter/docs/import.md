# Importing from Mailchimp

A one-time import of a Mailchimp audience into one of the tenant's newsletter
lists, keeping each contact's status and tags. The screen is
`/admin/newsletter/import` (`newsletter.manage`); the routes are under
`/api/newsletter/imports`. There is no Mailchimp API and no API key: the source
is the file Mailchimp exports, uploaded through the browser.

## What to export

In Mailchimp: *Audience -> Export audience*, then download the ZIP. Upload the
ZIP itself, or the CSV files inside it (up to 4). Mailchimp writes one file per
kind of contact, and the kind is read from the file name's prefix
(`subscribed`, `unsubscribed`, `cleaned`, `nonsubscribed`, case-insensitive;
`unsubscribed` is tested before `subscribed`). A file without such a prefix is
classified by its columns (`UNSUB_TIME` is unsubscribed, `CLEAN_TIME` is
cleaned), else it is subscribed.

**Segments are not exported.** Mailchimp's export carries each contact's own
tags only. The preview lists the tag values it found, so a segment can be
recreated from them on the Segments screen afterwards.

## What each file becomes

| Mailchimp file | In records | In newsletter |
| --- | --- | --- |
| subscribed | a `confirmed` subscriber | nothing |
| unsubscribed | an `unsubscribed` record (address only) | an `unsubscribed` suppression, source `import` |
| cleaned | no subscriber | an `imported_cleaned` suppression |
| nonsubscribed | nothing: listed as `ignored`, no row staged | nothing |

Both suppression kinds are written at once, in the same transaction as records'
change, so the address is suppressed tenant-wide without waiting for the hourly
reconcile.

### The decision table

Records decides from the record that holds the address (trash included), under
the subscriber's row lock. Newsletter then adds its suppressions.

| Records has | Mailchimp subscribed | Mailchimp unsubscribed | Mailchimp cleaned |
| --- | --- | --- | --- |
| nothing | create `confirmed` | create `unsubscribed`; suppression | suppression only |
| `confirmed` | append new tags, fill only empty mapped fields (`updated` / `unchanged`) | unsubscribe it, unless it was confirmed after `UNSUB_TIME` (`kept_confirmed`, no suppression) | suppression |
| `pending` | no write (`kept_pending`) | no write; suppression | suppression |
| `unsubscribed` | no write (`kept_unsubscribed`), never resubscribed | no write; suppression | suppression |
| trashed | no write (`trashed`) | no write; suppression | suppression |

Before records is called, a subscribed address is skipped (counted as skipped,
never created) when newsletter already suppresses it, for any reason on any
list, **or** when records holds it `unsubscribed` on any of the tenant's lists,
trash included (`opted_out_anywhere`). An opted-out or bounced person never
becomes a mailable record.

**An import never moves `pending` to `confirmed`, never clears a suppression and
never resubscribes an opted-out person.** A person who signed up on the new site
and has not clicked the confirm link keeps their pending signup. Only a
double-opt-in confirmation clears a suppression, and an import is not one.

### Precedence

When one address is in several files, the strongest kind wins: cleaned, then
unsubscribed, then subscribed. A re-run of a finished export changes no data:
every address comes back `unchanged` or `kept_*`, and the suppression writes
ignore rows that already exist.

### Values written for a new subscriber

| Field | Value |
| --- | --- |
| email | the lowercased address |
| status | `confirmed` |
| confirmed at | `CONFIRM_TIME`, else `OPTIN_TIME`, else the import time; never later than now |
| consent at | `OPTIN_TIME`, else the import time |
| consent text | `Imported from Mailchimp on <YYYY-MM-DD>` (stored in English) |
| locale | records' default content locale |
| consent IP hash, source page | none |

An unsubscribed record gets status `unsubscribed`, the unsubscribe time
(`UNSUB_TIME`, else now) and nothing else. Records' `created_at` is the import
time, so a segment's "Signed up" rule means "added" for imported people.

## Parsing

- UTF-8, with or without a BOM; anything else refuses the file
  (`import_not_utf8`, with the line).
- The delimiter is sniffed from the header line among `,` `;` and tab, so a
  German Excel re-save works.
- Headers are matched case-insensitively after trimming. The email column is the
  first of `Email Address`, `Email`, `E-mail`, `E-mail Address`,
  `E-Mail-Adresse`, `email_address`; a file without one is refused
  (`import_no_email_column`). A second email-like column is not offered for
  mapping.
- A header used by two columns (two `Phone` columns, a second `TAGS`, a second
  `Email Address`; compared after trimming, dropping a BOM and case-folding; empty headers
  aside) refuses the file (`import_duplicate_column`, 422): the
  later cell would silently overwrite the earlier one. The error names the
  header, never a cell.
- `OPTIN_TIME`, `CONFIRM_TIME`, `UNSUB_TIME` and `CLEAN_TIME` are Mailchimp's
  `YYYY-MM-DD HH:MM:SS` in UTC; anything else reads as missing.
- Mailchimp's own bookkeeping columns (rating, IPs, coordinates, campaign ids,
  unsubscribe reasons...) are not offered for mapping.

### Limits

Constants in `sm_newsletter/imports/constants.py`, not settings.

| Limit | Value |
| --- | --- |
| Upload | 50 MiB (the route's body ceiling is that plus 1 MiB of multipart framing) |
| Files | 4 parts, or 1 ZIP holding at most 4 CSV files |
| ZIP entries | 16 (any kind; only the CSVs count toward the 4 files) |
| One entry, declared uncompressed | 200 MiB |
| All entries, declared | 400 MiB |
| Compression ratio | 200 |
| Rows staged in all | 250 000 |
| Columns | 200 |
| One cell | 4 096 characters |
| One line | 4 MiB |
| Header text kept in a field key or error | 200 characters |
| Tags per row | 50 |
| One tag | 1 to 100 characters, printable only (`str.isprintable()`: no control, format or separator characters other than a plain space) |
| Distinct tag labels in one upload | 500 |

An encrypted ZIP entry, a compression other than stored or deflate, a declared
size or ratio over the caps, or an entry whose header lies about its size (the
read stops at the declared size, or the CRC fails) refuses the archive
(`import_zip_unsafe`). Folders, `__MACOSX/`, dot-files and non-`.csv` entries
are skipped. More than 500 distinct tag labels refuses the upload rather than
dropping some silently.

## Mapping

After the upload the screen shows each file's kind and counts (rows, duplicates,
invalid) and the columns found. Any column that is not Mailchimp bookkeeping can
be mapped to one of the list's **ordinary** fields of type `text`, `longtext`,
`email`, `url` or `select`, at most one column per field. A `select` value must
match a choice value or label. `First Name` / `Vorname` and `Last Name` /
`Nachname` map to `first_name` and `last_name` by default when the list has
them.

A value the field refuses (too long, not a choice) is dropped for that row. The
row is still imported, and a row error names the field. Where the subscriber
already exists, a merge validates the same way and the stored value stays.

### Tags

Tags come only from the `TAGS` column. A cell such as `"VIP","Customers, 2020"`
is read as a list; each tag is trimmed and validated. Tags are a switch, on by
default when tags were found and the list can hold them.

- The list's `tags` multiselect gets the new choices once, before the first
  batch. A choice's **value** is deterministic and never contains a comma:
  an existing choice with the same label is reused; else the label itself when
  it has no comma and is not taken; else the label's slug plus `-` and 8 hex
  characters of its SHA-256, with `-2`, `-3`… appended while another choice
  holds that too. Labels stay as written, so `Customers, 2020` and
  `Customers; 2020` stay distinct. The rule is records' (`tag_choice_values`):
  the preview shows its values against the choices at staging, and the tags
  step hands records the labels (`add_tag_choices`), which reads the choices,
  resolves every label and appends the new ones under one type lock and
  returns the mapping the import then uses, so a choice added meanwhile under
  another label is never mistaken for this import's.
- A list without a `tags` field gets one only while it holds **no records,
  trash included**. Otherwise tags are unavailable and the screen says to add a
  `tags` multiselect in records first.

## Creating the target list

*New list* on the screen (and `POST /api/newsletter/lists`) creates a records
subscription list with `first_name` and `last_name` (text, at most 100
characters) and records' preset defaults: signup form disabled, double opt-in
on, shown in the records menu. There is no `tags` field until an import with
tags adds one.

**Creating a list needs only `newsletter.manage`**, so a newsletter manager can
create a records list type (subscription kind only) without
`records.manage_types`.

## Counts

Every staged row lands in exactly one count:

| Count | Meaning |
| --- | --- |
| created | records created a subscriber |
| updated | an existing subscriber got new tags or filled fields |
| skipped | a subscribed row that wrote nothing (`unchanged`, `kept_*`, trashed, already suppressed), and `kept_confirmed` |
| suppressed | every unsubscribed or cleaned row, new or not, so a re-run reports the same number |
| failed | records refused the row |

The upload also reports `invalid` and `duplicates`: refused while staging and
never staged.

## Errors and the CSV

A row error is `{file, line, code, field}`. `file` is the file's index; `code`
is from a fixed vocabulary (`invalid_email`, `cell_too_long`, `tag_invalid`,
`invalid_value`, `record_refused`, `tags_unavailable`). `field` is the list
field's key at apply time and, for a staging refusal, the column's header text
(capped at 200 characters), because staging does not know the mapping yet. **An
error never echoes a cell's value**, logs carry counts and the import id only,
and HTTP refusals name a file by index and line, never by name. The first 1 000
errors are kept. `GET /api/newsletter/imports/{id}/errors.csv` downloads them with the
file names. Free-text cells (file name, field) are always prefixed with `'` unless
empty or purely numeric; the other cells are prefixed when their left-stripped form
starts with `=`, `+`, `-`, `@`, tab, CR, LF or a full-width `＝ ＋ － ＠`. Every cell is
quoted and `;`, tab, CR and LF in a free-text cell become `_`, so a semicolon-locale parser cannot split a
cell into a formula.

## Workers, slices and the janitor

Uploading parses and stages the rows in the request, so the preview is exact.
Applying hands the import to the Celery task
`newsletter.run_import(tenant_id, import_id)` on the `newsletter` queue.

- The task binds the tenant (`tenant_scope`), claims a lease (5 minutes,
  renewed per batch) and works in slices of at most 45 seconds in batches of
  200 rows. At the end of a slice it releases the lease and enqueues the next
  slice. **Under Celery eager** (tests, e2e, a host without a broker) it runs
  every slice inline in the request.
- Each row's outcome is stored in the same transaction as its effects, so a
  crash rolls the batch back and the next claim redoes it. Every write after the
  claim is fenced on the lease owner; a worker that lost its lease writes
  nothing.
- Records holds its type lock for the whole batch (lookup, create, update), so
  signups to the list being imported wait up to one batch's transaction.
- **Admission holds until the batch commits.** A batch first takes records'
  per-address opt-out lock for every one of its addresses, in ascending key
  order (`lock_import_batch`: `pg_advisory_xact_lock` on Postgres), then the
  list's type lock, and only then reads newsletter's suppressions and records'
  opt-outs (`opted_out_anywhere`). Every unsubscribe, on any list, takes the
  same address lock before its own type and row locks, so an opt-out on list A
  either commits before the read (and the address is skipped on B) or waits for
  the batch, and then its mirror suppresses the address on B too. On SQLite the
  type lock's `UPDATE` is the database's write lock, taken before the read.
  Lock order: **address locks → type lock → row locks → suppression rows**.
  An unsubscribe of an address being imported waits up to one batch. A batch
  holds up to 200 advisory locks in Postgres' shared lock table, so running
  imports in parallel would need a look at `max_locks_per_transaction`.
- A failure is recorded on the import as `import_failed`; the log carries the
  class name and the import id only, never an address.
- The hourly `newsletter.import_janitor` beat task relaunches a `queued` or
  `running` import whose lease ran out (a lost message) and deletes staged or
  failed imports older than 24 hours. A staged import is timed from its
  creation, a failed one from when it failed, so "Apply again" has a full day.
  The delete repeats that test with the pass's own cutoff, so a job queued, or
  retried and failed again, since the pass read it is kept. A `queued` import
  is timed from its creation: one staged long ago and queued just now is
  relaunched by the next pass, which is harmless (a second launch of a job
  somebody runs answers `busy`).

## What an import publishes

**An import publishes no events.** No `SubscriptionChanged`, `RecordCreated` or
`RecordUpdated`: records' batch runs muted. Other consumers of records' events
do not see imported people or the opt-outs an import writes; newsletter's own
suppressions are written directly. This is also what makes "never emits
pending to confirmed" structural.

## What is stored

Uploaded rows are staged in `newsletter_import_row` (addresses, a few mapped
values, the outcome), the job in `newsletter_import`. **Staged addresses are
deleted when the import ends, or after 24 hours** if nobody applied it or it
failed. The counts, the kept errors and the tag labels found stay on the import.

## The end-to-end spec

`tests/e2e/newsletter.spec.ts` covers list creation, an import, a suppressed
address, a send to a tag, the report and an unsubscribe. It is opt-in with
`E2E_NEWSLETTER=1` and runs only in its own CI job, `E2E (newsletter)`, against
a non-bundle host with Celery eager and `SM_ENVIRONMENT=development` (the
`testing` environment serves pages from the Vite dev server under the strict
production CSP, which blanks the console). The bundle shards ignore it. It
sends mail through `POST /api/newsletter/outbox/dispatch`, which exists only
with the console transport, under Celery eager, with `SM_ENVIRONMENT`
`development` or `testing` (a 404 anywhere else, production included). Run it
locally with `E2E_NEWSLETTER=1 npx playwright test`.
