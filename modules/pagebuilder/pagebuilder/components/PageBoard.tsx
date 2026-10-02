import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { PageBoardCard } from './PageBoardCard';

/** The four stages `board.py` emits, and the copy each column carries.
 *
 * The server sends `stage.label` as English — it has no request locale to
 * resolve one with — so the heading is re-derived here from the stage *key*
 * instead, leaving the payload the API tests assert on untouched. The empty
 * line is a key of its own rather than "Nothing " plus a lowercased label:
 * lowercasing a translated noun is only safe in English. */
const STAGES: Record<string, { label: string; empty: string }> = {
  draft: { label: keys.pagebuilder.board.stage_draft, empty: keys.pagebuilder.board.empty_draft },
  scheduled: {
    label: keys.pagebuilder.board.stage_scheduled,
    empty: keys.pagebuilder.board.empty_scheduled,
  },
  in_review: {
    label: keys.pagebuilder.board.stage_in_review,
    empty: keys.pagebuilder.board.empty_in_review,
  },
  published: {
    label: keys.pagebuilder.board.stage_published,
    empty: keys.pagebuilder.board.empty_published,
  },
};

export interface BoardStage {
  key: string;
  label: string;
  total: number;
  items: PageRead[];
}

interface Props {
  stages: BoardStage[];
  search: string;
  /** The language that serves unprefixed — see PageBoardCard. */
  defaultLocale: string;
  /** The create control, passed in so the empty state offers the same dialog
   *  the header does rather than a second, divergent path to a new page. */
  newPageSlot?: React.ReactNode;
  onDelete: (page: PageRead) => Promise<unknown>;
  onPublish: (page: PageRead) => Promise<unknown>;
  onUnpublish: (page: PageRead) => Promise<unknown>;
}

/** The pages board: one column per pipeline stage.
 *
 * Columns, not a table, because the question this screen answers is "what is
 * where in the pipeline" — a count and a short list per stage answers it at a
 * glance, where a status column sorted among four others does not.
 *
 * Each column is capped server-side and says what it is not showing. A board
 * that paginated would be unreadable, and one that silently truncated would be
 * worse: "Published 31" over eight cards has to be explained on the card list,
 * not left for the reader to notice.
 */
export function PageBoard({
  stages,
  search,
  defaultLocale,
  newPageSlot,
  onDelete,
  onPublish,
  onUnpublish,
}: Props) {
  const { t } = useT();
  const empty = stages.every((stage) => stage.total === 0);

  if (empty) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <p className="font-medium">
          {search ? t(keys.pagebuilder.board.no_match) : t(keys.pagebuilder.board.empty_title)}
        </p>
        <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
          {search
            ? t(keys.pagebuilder.board.no_match_description)
            : t(keys.pagebuilder.board.empty_description)}
        </p>
        {!search && newPageSlot && <div className="mt-3 flex justify-center">{newPageSlot}</div>}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {stages.map((stage) => {
        const copy = STAGES[stage.key];
        const label = copy ? t(copy.label) : stage.label;
        return (
          <section
            key={stage.key}
            aria-label={t(keys.pagebuilder.board.stage_aria, { stage: label })}
            data-testid="board-stage"
            data-stage={stage.key}
            className="flex flex-col gap-2 rounded-lg bg-muted/40 p-3"
          >
            <header className="flex items-baseline justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide">{label}</h2>
              <span className="tabular-nums text-sm text-muted-foreground">{stage.total}</span>
            </header>

            {stage.items.length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                {copy ? t(copy.empty) : `Nothing ${stage.label.toLowerCase()}.`}
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {stage.items.map((page) => (
                  <PageBoardCard
                    key={page.id}
                    page={page}
                    stage={stage.key}
                    defaultLocale={defaultLocale}
                    onDelete={onDelete}
                    onPublish={onPublish}
                    onUnpublish={onUnpublish}
                  />
                ))}
              </ul>
            )}

            {stage.total > stage.items.length && (
              <Button
                type="button"
                variant="link"
                size="sm"
                className="self-start"
                onClick={() =>
                  router.get('/pagebuilder/', {
                    view: 'list',
                    status: statusFor(stage.key),
                    search,
                  })
                }
              >
                {t(keys.pagebuilder.board.more, { count: stage.total - stage.items.length })}
              </Button>
            )}
          </section>
        );
      })}
    </div>
  );
}

/** Which list-view status filter shows the rest of a column.
 *
 * Scheduled has no status of its own — it is a draft with a future date — so
 * "N more" from that column lands on the drafts and lets the reader take it
 * from there rather than on a filter that would return nothing.
 */
function statusFor(stage: string): string {
  if (stage === 'published') return 'published';
  if (stage === 'in_review') return 'submitted_for_review';
  return 'draft';
}
