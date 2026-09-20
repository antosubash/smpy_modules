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
  onGo,
}: {
  page: number;
  pageSize: number;
  total: number;
  capped: boolean;
  onGo: (page: number) => void;
}) {
  const { t } = useT();
  if (total <= pageSize) return null;
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
      <span>{pageInfo(t, rangeStart, rangeEnd, total, capped)}</span>
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
