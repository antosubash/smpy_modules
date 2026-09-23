import { useT } from '@simple-module-py/i18n';

import { filterErrorMessage, type ListUrlChange, listStatus } from '../utils/listing';
import type { RecordListPage } from '../utils/types';
import { RecordPagination } from './RecordPagination';

/**
 * Below the list: the live region that says what the last navigation did,
 * and the pager. Extracted from `pages/RecordList.tsx` for the 300-line cap
 * when the pager grew its cursor mode; the two read the same page and the
 * same refusal, so they moved together.
 */
export function RecordListFooter({
  records,
  total,
  errorReason,
  loading,
  goTo,
}: {
  records: RecordListPage;
  /** `records.total ?? 0` — exact, or the cap when `total_capped`. */
  total: number;
  /** `errors.filter`, whichever part of the query it refused. */
  errorReason: string | undefined;
  loading: boolean;
  goTo: (next: ListUrlChange) => void;
}) {
  const { t } = useT();
  // A cursor page with nothing to continue from — see `PagerProps.stopped`.
  const stopped = records.page === null && (Boolean(errorReason) || records.items.length === 0);
  return (
    <>
      {/* A filter, a sort or a page swaps the rows through a partial reload
          with no focus move, so a screen reader was never told the page had
          become a different page (UX-R15). U10: a refused filter used to
          announce "0 records, page 1 of 1" here — an assertion about data
          that was never queried — while a sighted user read the real reason
          in the amber banner above. Announce that reason instead when it's
          set, so both surfaces agree. */}
      <p className="sr-only" role="status" aria-live="polite" data-testid="records-list-status">
        {errorReason
          ? filterErrorMessage(t, errorReason)
          : listStatus(t, {
              count: records.items.length,
              page: records.page,
              pages: Math.max(1, Math.ceil(total / records.page_size)),
              capped: records.total_capped,
            })}
      </p>

      <RecordPagination
        page={records.page}
        pageSize={records.page_size}
        total={total}
        capped={records.total_capped}
        itemCount={records.items.length}
        nextCursor={records.next_cursor}
        stopped={stopped}
        loading={loading}
        onGo={(next) => goTo({ page: next })}
        onContinue={(cursor) => goTo({ after: cursor })}
        onPageSize={(size) => goTo({ page: 1, pageSize: size })}
      />
    </>
  );
}
