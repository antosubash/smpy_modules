import { useT } from '@simple-module-py/i18n';
import type { ReactNode } from 'react';

import { PAGE_SIZES } from '../utils/listing';
import { PagerButton } from './PagerButton';
import { PageSizeSelect } from './PageSizeSelect';
import { cursorPagerParts } from './RecordCursorPager';

// The footer treats the first size as "unset": a type small enough to fit on
// one page renders no footer at all unless the URL asked for another size,
// and would otherwise strand a reader who picked 100 with no control to go
// back to 25. Re-exported for the callers that imported it from here.
export { PAGE_SIZES };

// See `utils/list-errors.ts` for why `t` is typed this loosely.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
export type Translate = (...args: any[]) => string;

/** The footer's "Showing 1–25 of N" — or "of 10,000+" when the API capped
 *  the count (F4, `RecordsSettings.max_count`). Two calls and not one
 *  interpolation, for the reason `filterErrorMessage` above gives: the
 *  untranslated-string check reads `t()` calls, not a string chosen before
 *  one. `count` is formatted here rather than passed as a number so the
 *  ceiling reads as "10,000+" — which is also why this takes the loose
 *  `Translate` type the file already defines. */
function pageInfo(
  t: Translate,
  start: number,
  end: number,
  total: number,
  capped: boolean,
): string {
  if (capped) {
    return t('records.records.page_info_capped', {
      start,
      end,
      count: total.toLocaleString(),
      defaultValue: 'Showing {start}–{end} of {count}+',
    });
  }
  return t('records.records.page_info', {
    start,
    end,
    total,
    defaultValue: 'Showing {start}–{end} of {total}',
  });
}

/** What "N+" means, as a `title` on the whole footer line (UX-2) — the count
 *  stopped rather than the data, and nothing else on screen says so. */
function cappedHelp(t: Translate, total: number): string {
  return t('records.records.page_info_capped_help', {
    count: total.toLocaleString(),
    defaultValue: 'More than {count} records match; the count stops at {count}.',
  });
}

/** "Page 2 of 8" — or just "Page 2" when the total is the cap and not the
 *  count (F4), where a last page number would be a number that isn't one.
 *  Two `t()` calls for the reason `pageInfo` gives. */
function pagePosition(t: Translate, page: number, pages: number, capped: boolean): string {
  if (capped) {
    return t('records.records.page_position_capped', { page, defaultValue: 'Page {page}' });
  }
  return t('records.records.page_position', {
    page,
    pages,
    defaultValue: 'Page {page} of {pages}',
  });
}

export type PagerProps = {
  /** `null` on a page reached by cursor (`?after=`), which has no number —
   *  the footer's cursor mode. */
  page: number | null;
  pageSize: number;
  total: number;
  capped: boolean;
  /** How many rows this page actually rendered (`records.items.length`) —
   *  the range's end. On a capped listing `total` is the ceiling, not the
   *  real count, so `min(page*pageSize, total)` under-reports the last
   *  partial page by however far the real count ran past the cap (UX-2); the
   *  rows on screen are the one number that is always right. */
  itemCount: number;
  /** `RecordPage.next_cursor`: where "Next" continues once the numbered
   *  pages run out (a capped listing's last page) and on every cursor page.
   *  `null` means this page was the end of the list. */
  nextCursor?: string | null;
  /** U12: a page/size change is in flight — the controls ignore presses
   *  rather than invite a second click that races the first. They stay
   *  enabled (`aria-disabled`), so keyboard focus stays put (`PagerButton`). */
  loading?: boolean;
  onGo: (page: number) => void;
  /** A cursor page that shows nothing to continue from: refused, or past
   *  the last row. The empty box above says which and offers the way back,
   *  so the footer keeps only the page-size select — no "continues from
   *  here" sentence under a notice that says it can't, and no second
   *  "First page" (review 4, ux F5). */
  stopped?: boolean;
  /** Continues with `?after=<cursor>` — see `utils/listing.ts::listParams`. */
  onContinue?: (cursor: string) => void;
  /** Writes `?page_size=` and returns to page 1 — the row the reader was
   *  looking at is on a different page under a different size anyway. */
  onPageSize: (size: number) => void;
};

/**
 * The record list's footer: "Showing 1–25 of N", where in the run of pages
 * this one falls, the page buttons and the page-size select.
 *
 * Extracted from `pages/RecordList.tsx` for the 300-line cap when the total
 * stopped being a plain number (F4). `total` is what the API reported — the
 * exact count, or `RecordsSettings.max_count` when `capped` — and the
 * numbered pager reads that same value, so it pages to the cap and no
 * further. **Past the cap, "Next" continues by cursor**: on the cap's last
 * page, if the server says there is more (`nextCursor`), it writes
 * `?after=` instead of a page number, and the footer switches to its cursor
 * mode for every page after that.
 *
 * **Cursor mode** (`page === null`) has no numbers to show — no range, no
 * "Page N", no Previous and no Last, because a keyset page knows only what
 * follows it. It offers **First page** and **Next page**, and one sentence
 * saying the list carries on in the same order without page numbers. Back
 * is the browser's: every step is its own URL.
 *
 * "First"/"Last" and the size select are UX-R18: 180 records at 25 a page
 * put the last page seven clicks away, with no page number to say where you
 * were and no way to ask for a longer page. Both write the URL through the
 * caller, like every other list control (the URL is the state).
 *
 * Renders nothing when a single page holds everything *and* nobody asked for
 * a different page size — which is what the list did before, and keeps a
 * small type's screen free of chrome without stranding a reader who picked
 * 100 on a screen with no control to pick 25 again. Never in cursor mode,
 * though: a cursor page past the end is empty, and it still needs "First
 * page".
 */
export function RecordPagination(props: PagerProps) {
  const { t } = useT();
  const { page, pageSize, total, loading = false, onPageSize } = props;
  if (page !== null && total <= pageSize && pageSize === PAGE_SIZES[0]) return null;
  const parts = page === null ? cursorPagerParts(t, props) : numberedPagerParts(t, props, page);
  return (
    <div
      className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground"
      data-testid={parts.testId}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{parts.info}</div>
      <div className="flex flex-wrap items-center gap-3">
        <PageSizeSelect pageSize={pageSize} loading={loading} onPageSize={onPageSize} />
        <div className="space-x-2">
          {/* Keyed by role, in one tree for both modes: "Next" on the cap's
              last page and "Next page" on the cursor page it leads to are
              the same DOM node, so keyboard focus survives the switch
              (review 4, ux F2) — two pager components would remount it. */}
          {parts.actions.map((action) => (
            <PagerButton
              key={action.key}
              unavailable={action.unavailable}
              busy={loading}
              onPress={action.onPress}
            >
              {action.label}
            </PagerButton>
          ))}
        </div>
      </div>
    </div>
  );
}

/** One footer button: `key` is its role, shared by both modes. */
export type PagerAction = {
  key: 'first' | 'previous' | 'next' | 'last';
  label: string;
  unavailable?: boolean;
  onPress: () => void;
};

/** What a mode puts in the shared footer frame. */
export type PagerParts = { info: ReactNode; actions: PagerAction[]; testId?: string };

function numberedPagerParts(t: Translate, props: PagerProps, page: number): PagerParts {
  const { pageSize, total, capped, itemCount, nextCursor = null, onGo, onContinue } = props;
  const rangeStart = itemCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = itemCount === 0 ? 0 : rangeStart + itemCount - 1;
  // The last page the numbered pager reaches. On a capped listing that is
  // the last page *of the cap* — the same bound `Next` has always used.
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const onFirst = page <= 1;
  const onLast = page >= lastPage;
  // Past the cap's last page the rows go on; the count does not. The server
  // says whether there are more (`nextCursor`), and "Next" follows it.
  const continues = capped && onLast && nextCursor !== null && onContinue !== undefined;
  // A capped page *without* a cursor is short, so it is the list's end (the
  // server hands out a cursor for every full page, `_listing.py`): the real
  // count is this page's last row, and "26–40 of 32+" would be a range
  // running past its own total (review 4, ux F12). A full final page still
  // says "32+" — nothing on it can tell it is the last.
  const ended = capped && nextCursor === null && itemCount > 0;
  const count = ended ? rangeEnd : total;
  const inexact = capped && !ended;
  return {
    info: (
      <>
        <span title={inexact ? cappedHelp(t, total) : undefined}>
          {pageInfo(t, rangeStart, rangeEnd, count, inexact)}
        </span>
        <span data-testid="records-page-position">
          {pagePosition(t, page, ended ? page : lastPage, inexact)}
        </span>
      </>
    ),
    actions: [
      {
        key: 'first',
        label: t('records.records.first', { defaultValue: 'First' }),
        unavailable: onFirst,
        onPress: () => onGo(1),
      },
      {
        key: 'previous',
        label: t('records.records.previous', { defaultValue: 'Previous' }),
        unavailable: onFirst,
        onPress: () => onGo(page - 1),
      },
      {
        key: 'next',
        label: t('records.records.next', { defaultValue: 'Next' }),
        unavailable: onLast && !continues,
        onPress: () => (continues ? onContinue(nextCursor) : onGo(page + 1)),
      },
      {
        key: 'last',
        label: t('records.records.last', { defaultValue: 'Last' }),
        unavailable: onLast,
        onPress: () => onGo(lastPage),
      },
    ],
  };
}
