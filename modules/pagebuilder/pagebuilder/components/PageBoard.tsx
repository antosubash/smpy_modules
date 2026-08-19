import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageRead } from '../utils/api';
import { PageBoardCard } from './PageBoardCard';

export interface BoardStage {
  key: string;
  label: string;
  total: number;
  items: PageRead[];
}

interface Props {
  stages: BoardStage[];
  search: string;
  onDelete: (page: PageRead) => Promise<unknown>;
  onPublish: (page: PageRead) => Promise<unknown>;
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
export function PageBoard({ stages, search, onDelete, onPublish }: Props) {
  const empty = stages.every((stage) => stage.total === 0);

  if (empty) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <p className="font-medium">{search ? 'No pages match this search' : 'No pages yet'}</p>
        <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
          {search
            ? 'Try a shorter search, or switch to the list view to filter by status.'
            : "Pages are the site's own content — everything outside the news feed. Nothing is published, so /p/* returns 404 for now."}
        </p>
        {!search && (
          <Button className="mt-3" onClick={() => router.visit('/pagebuilder/new')}>
            New page
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {stages.map((stage) => (
        <section
          key={stage.key}
          aria-label={`${stage.label} pages`}
          data-testid="board-stage"
          data-stage={stage.key}
          className="flex flex-col gap-2 rounded-lg bg-muted/40 p-3"
        >
          <header className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide">{stage.label}</h2>
            <span className="tabular-nums text-sm text-muted-foreground">{stage.total}</span>
          </header>

          {stage.items.length === 0 ? (
            <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
              Nothing {stage.label.toLowerCase()}.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {stage.items.map((page) => (
                <PageBoardCard
                  key={page.id}
                  page={page}
                  stage={stage.key}
                  onDelete={onDelete}
                  onPublish={onPublish}
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
                router.get('/pagebuilder/', { view: 'list', status: statusFor(stage.key), search })
              }
            >
              {stage.total - stage.items.length} more →
            </Button>
          )}
        </section>
      ))}
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
