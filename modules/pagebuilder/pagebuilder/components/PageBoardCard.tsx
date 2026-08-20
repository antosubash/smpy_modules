import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageRead } from '../utils/api';
import { ConfirmDialog } from './ConfirmDialog';

/** "1 Sep, 09:00" — when a scheduled draft flips itself. */
function whenLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "in 21d" / "2d ago", from a full timestamp. */
function relative(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const days = Math.round((then - Date.now()) / 86_400_000);
  if (days === 0) return 'today';
  return days > 0 ? `in ${days}d` : `${-days}d ago`;
}

interface Props {
  page: PageRead;
  stage: string;
  onDelete: (page: PageRead) => Promise<unknown>;
  onPublish: (page: PageRead) => Promise<unknown>;
  onUnpublish: (page: PageRead) => Promise<unknown>;
}

/** One page on the board. The line under the title says the thing that stage
 *  actually cares about — when a scheduled page fires, when a draft was last
 *  touched, whether a published page has unpublished edits waiting. */
export function PageBoardCard({ page, stage, onDelete, onPublish, onUnpublish }: Props) {
  const scheduled = stage === 'scheduled';
  const published = page.status === 'published';

  const meta = scheduled
    ? `publishes ${whenLabel(page.publish_at)} · ${relative(page.publish_at)}`
    : `/p/${page.slug}${page.updated_at ? ` · ${relative(page.updated_at)}` : ''}`;

  return (
    <li
      data-testid="board-card"
      data-slug={page.slug}
      className="rounded-md border bg-card p-3 shadow-sm"
    >
      <button
        type="button"
        onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        className="block w-full text-left font-medium hover:underline"
      >
        {page.title || 'Untitled page'}
      </button>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">{meta}</p>

      <div className="mt-2 flex flex-wrap gap-1">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        >
          Edit
        </Button>

        {!published && (
          <Button type="button" size="sm" onClick={() => void onPublish(page).catch(() => {})}>
            {scheduled ? 'Publish now' : 'Publish'}
          </Button>
        )}

        {published && (
          <Button type="button" size="sm" variant="outline" asChild>
            <a href={`/p/${page.slug}`} target="_blank" rel="noopener noreferrer">
              View
            </a>
          </Button>
        )}

        {published && (
          <ConfirmDialog
            // Medium: it takes effect publicly and at once, but nothing is
            // lost — which is the distinction the copy has to carry, or people
            // read "unpublish" as "delete".
            level="medium"
            title={`Take “${page.title}” offline?`}
            description={
              <>
                <code>/p/{page.slug}</code> starts answering 404 immediately. Your content is kept —
                this becomes a draft you can republish.
              </>
            }
            confirmLabel="Unpublish"
            onConfirm={() => onUnpublish(page)}
            trigger={
              <Button type="button" size="sm" variant="ghost">
                Unpublish
              </Button>
            }
          />
        )}

        <ConfirmDialog
          // Deleting a published page is the design's high blast radius: it is
          // live, it is linked, and the URL starts answering 404 immediately.
          // The typed slug is what separates it from deleting a draft nobody
          // has ever seen.
          level={published ? 'high' : 'low'}
          confirmPhrase={published ? page.slug : undefined}
          title={`Delete "${page.title}"?`}
          description={
            published ? (
              <>
                This page is published. <code>/p/{page.slug}</code> starts answering 404 the moment
                you confirm. It goes to the trash for 30 days, and after that it is gone.
              </>
            ) : (
              <>
                It was never published, so nothing on the site changes. It goes to the trash for 30
                days.
              </>
            )
          }
          confirmLabel="Delete"
          onConfirm={() => onDelete(page)}
          trigger={
            <Button type="button" size="sm" variant="ghost" className="text-destructive">
              Delete
            </Button>
          }
        />
      </div>
    </li>
  );
}
