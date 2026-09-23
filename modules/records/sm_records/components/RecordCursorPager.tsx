import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import { PageSizeSelect } from './PageSizeSelect';
import type { PagerProps } from './RecordPagination';

/**
 * The footer's cursor mode — `RecordPagination` renders this for a page
 * reached by `?after=` (`page: null`). See there for why it has no range, no
 * page number, no Previous and no Last: a keyset page knows only what follows
 * it. "First page" leaves the cursor behind; "Next page" follows
 * `next_cursor` and is disabled once a page arrives without one — the end of
 * the list.
 */
export function CursorPager({
  pageSize,
  nextCursor = null,
  loading = false,
  onGo,
  onContinue,
  onPageSize,
}: PagerProps) {
  const { t } = useT();
  return (
    <div
      className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground"
      data-testid="records-cursor-pager"
    >
      <p data-testid="records-page-cursor">
        {t('records.records.cursor_info', {
          defaultValue: 'The list continues in the same order from here, without page numbers.',
        })}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <PageSizeSelect pageSize={pageSize} loading={loading} onPageSize={onPageSize} />
        <div className="space-x-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={() => onGo(1)}
          >
            {t('records.records.first_page', { defaultValue: 'First page' })}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={nextCursor === null || onContinue === undefined || loading}
            onClick={() => nextCursor !== null && onContinue?.(nextCursor)}
          >
            {t('records.records.next_page', { defaultValue: 'Next page' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
