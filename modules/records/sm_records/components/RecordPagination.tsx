import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

// See `pages/RecordList.tsx` for why `t` is typed this loosely.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

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

/**
 * The record list's footer: "Showing 1–25 of N" and the two page buttons.
 *
 * Extracted from `pages/RecordList.tsx` for the 300-line cap when the total
 * stopped being a plain number (F4). `total` is what the API reported — the
 * exact count, or `RecordsSettings.max_count` when `capped` — and every
 * calculation here reads that same value, so a capped listing pages to the
 * cap and no further. Walking past it is what `RecordPage.next_cursor` and
 * `?after=` are for (F11); the admin UI shows numbered pages and does not.
 *
 * Renders nothing when there is only one page, which is what the list did
 * before and keeps a small type's screen free of chrome.
 */
export function RecordPagination({
  page,
  pageSize,
  total,
  capped,
  itemCount,
  onGo,
}: {
  page: number;
  pageSize: number;
  total: number;
  capped: boolean;
  /** How many rows this page actually rendered (`records.items.length`) —
   *  the range's end. On a capped listing `total` is the ceiling, not the
   *  real count, so `min(page*pageSize, total)` under-reports the last
   *  partial page by however far the real count ran past the cap (UX-2); the
   *  rows on screen are the one number that is always right. */
  itemCount: number;
  onGo: (page: number) => void;
}) {
  const { t } = useT();
  if (total <= pageSize) return null;
  const rangeStart = itemCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = itemCount === 0 ? 0 : rangeStart + itemCount - 1;
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
      <span title={capped ? cappedHelp(t, total) : undefined}>
        {pageInfo(t, rangeStart, rangeEnd, total, capped)}
      </span>
      <div className="space-x-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onGo(page - 1)}
        >
          {t('records.records.previous', { defaultValue: 'Previous' })}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page * pageSize >= total}
          onClick={() => onGo(page + 1)}
        >
          {t('records.records.next', { defaultValue: 'Next' })}
        </Button>
      </div>
    </div>
  );
}
