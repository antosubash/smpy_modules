import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@simple-module-py/ui/components/ui/dropdown-menu';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';
import { type ArticleRead, formatArticleDate, relativeDay } from '../utils/api';
import { ConfirmDialog } from './ConfirmDialog';

/** The article editor — category, tags, date, byline and feed behaviour. The
 *  body has a canvas of its own, so it is edited one link further in. */
const articleSettingsUrl = (id: number) => `/admin/news/articles/${id}/edit`;

/** `2026-02-01T00:00:00` -> `2026-02-01`, which is what <input type=date> wants. */
function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

/** The one-line status the card carries under its metadata.
 *
 * `published_at` is the editorial display date, not a schedule — the field
 * that actually drives auto-publish is `publish_at`, set from ScheduleCard
 * and not read anywhere in this list. A future `published_at` used to read
 * as "publishes {date}", which promised something this row cannot keep: an
 * editor could set a future display date, see "publishes …" and believe the
 * article will go live on its own when nothing here does that.
 */
function statusLine(article: ArticleRead): string {
  const when = article.published_at;

  if (article.status === 'published') {
    return when ? `Published · ${relativeDay(when)}` : 'Published · no date';
  }
  if (article.status === 'submitted_for_review') return 'Pending review';
  return when ? `Draft · dated ${relativeDay(when)}` : 'Draft · undated';
}

interface Props {
  article: ArticleRead;
  busy: boolean;
  /** id of a <datalist> of existing category names, offered while typing. */
  suggestionsId?: string;
  /** Whether the viewer holds `news.publish`. Hard delete needs it — the
   *  same pair the backend requires for `purge` — so a `news.edit`-only
   *  author gets the recoverable `onTrash` instead of a button that 403s. */
  canPublish: boolean;
  onSave: (id: number, category: string, publishedAt: string | null) => void;
  onDelete: (id: number) => void;
  onTrash: (id: number) => Promise<unknown>;
  onPublish: (article: ArticleRead) => Promise<unknown>;
}

/** One article as a card row: title carries the weight, metadata sits quiet
 *  underneath, and the actions live on the row rather than behind a menu.
 *
 *  Category and date edit in place. Opening a whole editor to change a chip is
 *  the thing this list exists to avoid — the body is edited in pagebuilder, so
 *  if these two fields also needed a round trip the list would have no job.
 */
export function ArticleRow({
  article,
  busy,
  suggestionsId,
  canPublish,
  onSave,
  onDelete,
  onTrash,
  onPublish,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(article.category);
  const [date, setDate] = useState(toDateInput(article.published_at));

  const dirty = category !== article.category || date !== toDateInput(article.published_at);
  const isDraft = article.status === 'draft';
  const dateLabel = formatArticleDate(article.published_at) || 'no date';

  const save = () => {
    onSave(article.id, category, date ? `${date}T00:00:00Z` : null);
    setEditing(false);
  };

  return (
    <li
      data-testid="article-row"
      data-slug={article.slug}
      // Wraps rather than squeezing: below `sm` the actions take their own
      // line instead of competing with the headline for the same 360px. The
      // design moves them to a swipe or long-press there, which is smaller but
      // reachable by neither keyboard nor screen reader — and undiscoverable
      // for everyone else.
      className="flex flex-wrap items-start gap-x-4 gap-y-3 rounded-lg border bg-card p-3"
    >
      {article.cover_image_url ? (
        <img
          src={article.cover_image_url}
          alt=""
          className="h-14 w-20 shrink-0 rounded object-cover"
        />
      ) : (
        <div
          aria-hidden
          className="flex h-14 w-20 shrink-0 items-center justify-center rounded bg-muted text-xs text-muted-foreground"
        >
          no image
        </div>
      )}

      <div className="min-w-0 flex-1">
        <a
          href={articleSettingsUrl(article.id)}
          className="font-medium hover:underline"
          data-testid="article-title"
        >
          {article.title || 'Untitled article'}
        </a>

        {editing ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Input
              aria-label={`Category for ${article.title}`}
              value={category}
              disabled={busy}
              list={suggestionsId}
              placeholder="Uncategorised"
              onChange={(e) => setCategory(e.target.value)}
              className="h-8 w-44"
            />
            <Input
              type="date"
              aria-label={`Date for ${article.title}`}
              value={date}
              disabled={busy}
              onChange={(e) => setDate(e.target.value)}
              className="h-8 w-40"
            />
            <Button type="button" size="sm" disabled={busy || !dirty} onClick={save}>
              Save
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setCategory(article.category);
                setDate(toDateInput(article.published_at));
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            {/* The accessible name starts with the visible text on purpose.
                An aria-label that replaced it would satisfy a screen reader
                and break voice control — "click Research" would match nothing
                (WCAG 2.5.3, label in name). */}
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              aria-label={`${article.category || 'Uncategorised'} — edit category and date`}
              className="rounded-full border px-2 py-0.5 text-xs hover:bg-muted"
            >
              {article.category || 'Uncategorised'}
            </button>
            <span>·</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              aria-label={`${dateLabel} — edit category and date`}
              className="hover:underline"
            >
              {dateLabel}
            </button>
            <span>·</span>
            <span className="truncate">{article.url}</span>
          </div>
        )}

        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{statusLine(article)}</span>
          {/* A state, not a fault. Publishing snapshots the body, so an author
              who keeps writing leaves the row saying "Published" about a
              document readers have never seen — truthfully, and about the
              wrong one. Neutral chrome rather than a warning colour: an
              article with edits in progress is the ordinary case, and the
              only thing this has to do is stop "Published" from being read
              as "up to date". */}
          {article.has_unpublished_changes && (
            <span
              data-testid="unpublished-changes"
              className="rounded-full border px-2 py-0.5 font-medium text-foreground"
            >
              Unpublished edits
            </span>
          )}
        </p>
      </div>

      <div className="flex w-full shrink-0 items-center justify-end gap-1 sm:w-auto">
        <Button type="button" size="sm" variant="outline" asChild>
          <a href={articleSettingsUrl(article.id)}>Edit</a>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              aria-label={`More actions for ${article.title}`}
            >
              ···
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isDraft && (
              <DropdownMenuItem onSelect={() => void onPublish(article).catch(() => {})}>
                Publish now
              </DropdownMenuItem>
            )}
            {article.status === 'published' && (
              <DropdownMenuItem asChild>
                <a href={article.url} target="_blank" rel="noopener noreferrer">
                  View on the site
                </a>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <a href={article.edit_url}>Edit the body</a>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setEditing(true)}>
              Edit category and date
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {canPublish ? (
          <ConfirmDialog
            // Medium, where this used to be low. "Detach" removed news' metadata
            // and left the document standing in pagebuilder, so it cost nothing
            // that could not be re-attached. There is no second document now —
            // the body is this row — so the same button destroys the article.
            //
            // Gated on `canPublish`: the backend requires `news.publish` here,
            // the same pair `purge` carries, because a hard delete is the one
            // action with no way back. An author with `news.edit` alone gets
            // the recoverable door below instead.
            level="medium"
            title={`Delete "${article.title}"?`}
            description="The article and its body are removed, and its public URL stops working. This cannot be undone from here."
            confirmLabel="Delete"
            onConfirm={async () => onDelete(article.id)}
            trigger={
              <Button type="button" size="sm" variant="ghost" disabled={busy}>
                Delete
              </Button>
            }
          />
        ) : (
          <ConfirmDialog
            // Medium for a published article — trashing takes it off the
            // public site immediately, same as unpublish, even though it is
            // fully reversible. Low would undersell that. A draft that was
            // never public fits "low" on the same scale, so it gets it.
            level={article.status === 'published' ? 'medium' : 'low'}
            title={`Move "${article.title}" to trash?`}
            description="It comes off the public site and out of this list. Restore it from Trash to put it back exactly as it was — trashing does not free its URL for reuse."
            confirmLabel="Move to trash"
            onConfirm={async () => onTrash(article.id)}
            trigger={
              <Button type="button" size="sm" variant="ghost" disabled={busy}>
                Move to trash
              </Button>
            }
          />
        )}
      </div>
    </li>
  );
}
