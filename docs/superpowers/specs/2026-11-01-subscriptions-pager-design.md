# Subscriptions pager (#283)

## Goal and scope

The admin Subscriptions screen (`/admin/billing/subscriptions`) shows the first
200 rows, then a "first 200, search to narrow" notice; the rest are reachable
only through the API's `offset`. Give the screen real page navigation, in both
subject modes (organisations, and users when `subject_mode = user`).

Out of scope: changing the JSON API's shape (`GET /api/billing/admin/subscriptions`
keeps returning a bare list with `offset`, so no client breaks), sorting by
column, a page-size picker.

## Approach

Copy the billing Usage screen, the module's own paged admin list: the view
reads `page`, returns a `Paged<SubscriptionRow>` (`items`, `total`, `page`,
`per_page`, `pages`), and the page renders the framework's `PaginationBar`
under the table with `hideWhenSinglePage`. The page served is clamped with
`metering.report.page_numbers`, so a stale link lands on the last page.

Rejected:
- Keyset/cursor paging (records' style): the list is ordered by name/email,
  is a few thousand rows at most, and offset paging is what Usage already does.
- "Load more" with no total: no page count, and it differs from the Usage screen.

## Design

- **Count.** `admin.subscription_count(db, app, *, status, q) -> int` counts
  what `subscription_rows` would list, with the same joins and filters. The
  filter-building moves into one helper per mode (tenant query in `admin.py`,
  user query in `admin_users.py`) used by both the rows and the count, so the
  two can't drift.
- **View.** `subscriptions_page` reads `page` (bad or < 1 → 1), serves
  `per_page = 50` (`c.ADMIN_PAGE_SIZE`), and sends `subscriptions: Paged<…>`
  instead of `rows` and `row_limit`. Status and `q` are kept across pages;
  changing either goes back to page 1.
- **UI.** `Subscriptions.tsx` takes `subscriptions`, builds its query like
  Usage's `query()` (leaving page 1 out of the URL) and renders
  `PaginationBar`. The 200-row notice and its `limit_notice` key go (en and de);
  `SubscriptionsFilters` loses `rowCount`/`rowLimit`.
- **API.** Unchanged. `ADMIN_ROW_LIMIT` stays its page size.

## Decisions made

- 50 rows per page (Usage uses 25 for events; a subscription row is one line,
  and 50 keeps most demo hosts on one page).
- The pager shows only when there is more than one page.
- No total in the heading; `PaginationBar` already shows the range and total.

## Testing

- Python: count matches the rows in both modes with status and `q`; the view
  serves page 2 of 51+ rows, clamps a page past the end to the last page, and
  treats `page=abc` as 1; the existing `offset` API test stays green.
- Vitest: the page renders the pager only with more than one page, and a page
  click visits `?page=2` keeping `status` and `q`; filters go back to page 1.
- E2E: extend `billing-user.spec.ts` (user mode, it already seeds many users)
  to step to page 2. QA covers both modes in the browser.

## Risks

- The count costs a second query per screen load; it is one `COUNT(*)` over
  the same joins, as Usage does. No index changes.
