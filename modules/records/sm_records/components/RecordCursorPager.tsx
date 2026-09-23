import type { PagerParts, PagerProps, Translate } from './RecordPagination';

/**
 * The footer's cursor mode — what `RecordPagination` shows for a page
 * reached by `?after=` (`page: null`). See there for why it has no range, no
 * page number, no Previous and no Last: a keyset page knows only what follows
 * it. "First page" leaves the cursor behind; "Next page" follows
 * `next_cursor` and is unavailable once a page arrives without one — the end
 * of the list.
 *
 * Parts for `RecordPagination`'s one footer frame rather than a component of
 * its own, so the numbered "Next" that leads here and this "Next page" are
 * one button and keep keyboard focus (`PagerButton`).
 */
export function cursorPagerParts(
  t: Translate,
  { nextCursor = null, stopped = false, onGo, onContinue }: PagerProps,
): PagerParts {
  if (stopped) return { testId: 'records-cursor-pager', info: null, actions: [] };
  return {
    testId: 'records-cursor-pager',
    info: (
      <p data-testid="records-page-cursor">
        {t('records.records.cursor_info', {
          defaultValue: 'The list continues in the same order from here, without page numbers.',
        })}
      </p>
    ),
    actions: [
      {
        key: 'first',
        label: t('records.records.first_page', { defaultValue: 'First page' }),
        onPress: () => onGo(1),
      },
      {
        key: 'next',
        label: t('records.records.next_page', { defaultValue: 'Next page' }),
        unavailable: nextCursor === null || onContinue === undefined,
        onPress: () => {
          if (nextCursor !== null) onContinue?.(nextCursor);
        },
      },
    ],
  };
}
