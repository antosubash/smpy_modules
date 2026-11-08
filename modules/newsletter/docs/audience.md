# Audiences, segments, subscribers and suppressions

Who a campaign goes to, how people are found and managed, and how a suppression
is seen and lifted. Subscribers still live in `simple_module_records`; newsletter
reads and writes them only through `sm_records.contracts.newsletter` and
`sm_records.contracts.newsletter_admin`.

## Segments

A segment is a named, saved filter over one list: `rules` (what the editor shows,
`[{field, op, value}]`) and the `filters` they compile to (records' filter
grammar, `key:op:value`). One function writes both in one statement, so they
cannot drift; only `filters` is ever evaluated. The rules are in
`sm_newsletter/segments/rules.py`, the routes under `/api/newsletter/segments`
(read: `newsletter.view`; create, change, delete: `newsletter.edit`, and a
create on a list the caller cannot read is 403 `list_forbidden`).

- **AND only.** Every rule must hold. "Any of several values" is the `any`
  operator on one field (it compiles to `in`); OR across fields is not offered.
  At most 10 rules and 20 compiled terms.
- **Fields.** Every filterable field records reports for the list, of a type in
  the table below, except
  `sm_status` (there is no status rule: a campaign only mails `confirmed`
  subscribers), plus **Signed up**, records' `created_at`. For a person added by
  the Mailchimp import (PR 7) that is the import time, so "signed up since"
  means "added since".
- **Operators by field type.**

  | Field type | Operators |
  | --- | --- |
  | tags / multi-select | `any`, `all`, `none` |
  | select | `is`, `is_not`, `any` |
  | text, email, url | `is`, `is_not`, `contains`, `starts_with` |
  | number, integer | `is`, `is_not`, `gt`, `gte`, `lt`, `lte` |
  | boolean | `is` |
  | date, datetime (incl. Signed up) | `before` (`lt`), `since` (`gte`) |

  `is` compiles to `eq` and `is_not` to `ne`; `all` is one `eq` term per value
  and `none` one `ne` term per value. A value is checked against the field's
  type and choices; errors name the rule's index and never echo the value.
- **Counts are "about".** The live count in the editor, the audience count and
  the audience picker are records' `count_subscribers` over the filters:
  confirmed, untrashed, matching. Suppressions are not subtracted, so the real
  number sent can be lower (see [`sending.md`](sending.md)). Incomplete rules
  are ignored by the preview.
- **Counting needs `records.view`.** A rule can name `sm_email` or any other
  subscriber field, so a count answers questions about subscribers (a run of
  `starts_with` counts would spell out addresses). Counts follow the
  subscriber screen:

  | Count | Route | Permission |
  | --- | --- | --- |
  | segment editor preview | `POST /segments/preview` | `newsletter.view` + `records.view` |
  | whole list | `GET /lists/{key}/audience-count?audience=all` | `newsletter.view` |
  | tag or segment | `GET /lists/{key}/audience-count?audience=tag:…\|segment:…` | `newsletter.view` + `records.view` |
  | send estimate | `GET /campaigns/{id}/estimate` | `newsletter.send`; `recipients` is `null` for a tag or segment audience without `records.view`, and the finish is computed on the whole list (an upper bound) |

  The segments and editor pages pass `can_count` (`records.view`), and without
  it the screens ask for no tag, segment or preview count and say only people
  who may view subscribers see it. A read-only campaign asks for no count at all.
- Deleting a segment that a campaign still names is `409 segment_in_use` while
  that campaign is a **draft**, **scheduled**, or **paused** before it started
  sending. Once a campaign has started, its audience is frozen and
  the segment can go.

## Audiences

A campaign's `audience` is one of:

- `all`: the whole list (confirmed subscribers);
- `tag:<value>`: exactly one tag, which must be a choice of the list's `tags`
  field (`422 unknown_tag` otherwise). Several tags is a segment;
- `segment:<id>`: a segment of the tenant that belongs to the campaign's list.
  A segment of another list is `422 segment_list_mismatch` only when the caller
  may read that list; one on a list they cannot read answers `422
  unknown_segment` exactly like a missing id, on the audience count, the
  subscriber search and a campaign PATCH alike (no existence oracle).

A PATCH validates the audience against the new or current list, and an invalid
one never echoes the submitted value; a kind without its value (`tag:`,
`segment:`) is `422 invalid_audience`, so a half-set audience is never stored.
In the editor, choosing "A tag" or "A segment" without picking one saves
nothing (the campaign keeps its old audience), and until a value is picked or
the choice is reverted the Send button is disabled and the send flush refuses.

**Scheduling snapshots the audience.** `schedule` resolves it to filter terms,
dry-runs `count_subscribers` with them (so a filter records cannot answer is a
422 at scheduling, not a pause at freeze), and stores them on the render row
(`audience_filters`) in the same transaction as `draft -> scheduled`. Freeze
reads that snapshot, together with the list, in the single read that claims the
freeze (so they belong to the claimed generation), and never the live segment.
Editing or deleting the segment afterwards changes nothing for a scheduled or
later campaign. **Unschedule, change, schedule again** picks up the new
definition. If records refuses a stored term at freeze the campaign pauses
(`list_unavailable` or `audience_unavailable`) or, for a temporary `reindexing`,
stays `scheduled` and a later tick retries; see [`sending.md`](sending.md).
Unschedule is also available from such a never-started pause.

## The subscriber screen

`/admin/newsletter/subscribers` (menu: `newsletter.view` and `records.view`).
Search is `POST /api/newsletter/lists/{key}/subscribers/search` with
`{status, q, tag, segment, offset, limit}` in the body, so an address is never in
a URL or an access log; the UI keeps the search text in component state.

| Action | Route | Needs |
| --- | --- | --- |
| search, detail | `POST .../subscribers/search`, `GET .../subscribers/{uuid}` | `newsletter.view` + `records.view` |
| add or remove tags | `POST .../subscribers/{uuid}/tags` | `newsletter.edit` + `records.view` |
| unsubscribe | `POST .../subscribers/{uuid}/unsubscribe` | `newsletter.manage` + `records.view` |

Every route also needs access to the list under records' `allowed_roles`: a list
the caller cannot read, or that is not a list, answers 404 (no oracle).

- **Detail shows aggregates only**, never a per-event list: campaigns sent, the
  last send's date and campaign, how many were opened (approximate, as in
  [`tracking.md`](tracking.md)) and clicked.
- **The `suppressed` flag.** A subscriber's `suppressed` flag is **tenant-wide**
  and reads "won't receive newsletters". Suppressions are tenant-wide (an opt-out
  on any list suppresses every list), so an admin of a readable list must be told
  that the address gets no mail. For a list the caller cannot read, the flag is
  the only thing disclosed: never the reason, source, list, date or fingerprint.
  The rows themselves are shown only for readable lists.
- **Admin unsubscribe** is records' unsubscribe plus newsletter's `unsubscribed`
  suppression (`source=admin`) in one transaction. `409 not_subscribed` when
  records did not write (pending, or already unsubscribed); a missing or trashed
  subscriber is 404.

## Suppressions

`/admin/newsletter/suppressions` (menu and API: `newsletter.manage`), API under
`/api/newsletter/suppressions`: the listing (`GET`), the lookup by address
(`POST /lookup`), the lift (`POST /{id}/lift`) and the audit log (`GET /lifts`).

- **Hashed.** A row holds `sha256(email.strip().lower())`, never an address.
  The screen shows a **fingerprint** (the first 12 hex characters), the reason,
  the list, the source and the date. Finding one address is a POST so it stays
  out of access logs. A row whose address nobody knows any more can be seen and
  counted, but not lifted.
- **Visibility.** A row is shown only when it is address-wide or its list is one
  the caller may read. A row whose list **no longer exists** is therefore hidden
  from every admin (it cannot be seen or lifted from the screen) yet still
  suppresses the address, until the list exists again.
- **Lift rules.** A lift needs `newsletter.manage`, the **address typed** (its
  hash must equal the row's), a note (1 to 500 characters) and the `version` of
  the row the admin saw (its `created_at`).

  | Reason | Lift |
  | --- | --- |
  | `complaint` | never: `409 lift_not_allowed`. A complaint is the recipient's report that the mail was unwanted; no later signup or admin note undoes it |
  | `hard_bounce` | yes; the dialog says the mailbox must be fixed first |
  | `imported_cleaned` | yes |
  | `unsubscribed` | only while records shows the address `confirmed`, untrashed, on that row's list with `sm_confirmed_at` **after** the row's `created_at`; else `409 opt_out_stands` |

  The `unsubscribed` case covers a stale opt-out on a single-opt-in list (records
  purged the old record; the new signup was `None -> confirmed`, which the mirror
  never clears) and a double-opt-in confirmation whose clearing event was lost.
  The dialog warns that without double opt-in anyone can type an address.
- **A lift is a conditional delete**: `DELETE ... WHERE id AND tenant_id AND
  created_at = version`. Zero rows (a repeat bounce or opt-out refreshed the row,
  or it is gone) is `409 suppression_changed`. The audit row
  (`newsletter_suppression_lift`: hash, reason, list, source, suppressed-at,
  lifted-at, `lifted_by`, note) is written in the same transaction.
- **Locks.** An `unsubscribed` lift decides and deletes while holding records'
  lock on the subscriber (`lock_confirmation`: records' type lock, then the row),
  which every records unsubscribe also takes (`opt_in.leave`,
  `transition(lock=True)`), so a concurrent opt-out makes the lift answer
  `opt_out_stands`. Lock order: records' type then row first, then newsletter
  rows (suppression, then the lift insert). The admin unsubscribe takes records'
  type and row, then upserts the suppression. Neither touches campaign, send or
  click rows, so the cancel order in [`sending.md`](sending.md) is unaffected.
  A new records path that unsubscribes must take the same lock.
- The hourly reconcile cannot undo an `unsubscribed` lift: it re-adds only
  records' `unsubscribed` subscribers, and a lift needs `confirmed`.
