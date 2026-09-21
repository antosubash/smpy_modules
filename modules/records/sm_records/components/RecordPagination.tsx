import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

/** The page sizes the footer offers. The first is the module's own default
 *  (`RecordsSettings.default_page_size`), which is also what the footer
 *  treats as "unset": a type small enough to fit on one page renders no
 *  footer at all unless the URL asked for another size, and would otherwise
 *  strand a reader who picked 100 with no control to go back to 25. */
export const PAGE_SIZES = [25, 50, 100] as const;

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

/**
 * The record list's footer: "Showing 1–25 of N", where in the run of pages
 * this one falls, the four page buttons and the page-size select.
 *
 * Extracted from `pages/RecordList.tsx` for the 300-line cap when the total
 * stopped being a plain number (F4). `total` is what the API reported — the
 * exact count, or `RecordsSettings.max_count` when `capped` — and every
 * calculation here reads that same value, so a capped listing pages to the
 * cap and no further. Walking past it is what `RecordPage.next_cursor` and
 * `?after=` are for (F11); the admin UI shows numbered pages and does not.
 *
 * "First"/"Last" and the size select are UX-R18: 180 records at 25 a page
 * put the last page seven clicks away, with no page number to say where you
 * were and no way to ask for a longer page. Both write the URL through the
 * caller, like every other list control (the URL is the state).
 *
 * Renders nothing when a single page holds everything *and* nobody asked for
 * a different page size — which is what the list did before, and keeps a
 * small type's screen free of chrome without stranding a reader who picked
 * 100 on a screen with no control to pick 25 again.
 */
export function RecordPagination({
  page,
  pageSize,
  total,
  capped,
  itemCount,
  onGo,
  onPageSize,
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
  /** Writes `?page_size=` and returns to page 1 — the row the reader was
   *  looking at is on a different page under a different size anyway. */
  onPageSize: (size: number) => void;
}) {
  const { t } = useT();
  if (total <= pageSize && pageSize === PAGE_SIZES[0]) return null;
  const rangeStart = itemCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = itemCount === 0 ? 0 : rangeStart + itemCount - 1;
  // The last page the numbered pager reaches. On a capped listing that is
  // the last page *of the cap* — the same bound `Next` has always used.
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const onFirst = page <= 1;
  const onLast = page >= lastPage;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span title={capped ? cappedHelp(t, total) : undefined}>
          {pageInfo(t, rangeStart, rangeEnd, total, capped)}
        </span>
        <span data-testid="records-page-position">{pagePosition(t, page, lastPage, capped)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Label htmlFor="records-page-size" className="font-normal">
            {t('records.records.page_size', { defaultValue: 'Per page' })}
          </Label>
          <NativeSelect
            id="records-page-size"
            className="w-auto"
            value={String(pageSize)}
            onChange={(e) => onPageSize(Number(e.target.value))}
          >
            {PAGE_SIZES.map((size) => (
              <NativeSelectOption key={size} value={String(size)}>
                {size}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <div className="space-x-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={onFirst}
            onClick={() => onGo(1)}
          >
            {t('records.records.first', { defaultValue: 'First' })}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={onFirst}
            onClick={() => onGo(page - 1)}
          >
            {t('records.records.previous', { defaultValue: 'Previous' })}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={onLast}
            onClick={() => onGo(page + 1)}
          >
            {t('records.records.next', { defaultValue: 'Next' })}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={onLast}
            onClick={() => onGo(lastPage)}
          >
            {t('records.records.last', { defaultValue: 'Last' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
