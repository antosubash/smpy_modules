import { ConfirmDialog } from '@simple-module-py/pagebuilder/pagebuilder/components/ConfirmDialog';
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

/** The article editor — category, tags, date, byline and feed behaviour. The
 *  body is a page, so it is edited one link further in. */
const articleSettingsUrl = (id: number) => `/news/articles/${id}/edit`;

/** `2026-02-01T00:00:00` -> `2026-02-01`, which is what <input type=date> wants. */
function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

/** The one-line status the card carries under its metadata.
 *
 * A future date on a draft is the design's "scheduled": there is no third
 * status, just a draft that will flip itself, and saying so is the only way
 * the list can be honest about a two-state pipeline.
 */
function statusLine(article: ArticleRead): string {
  const when = article.published_at;
  const ahead = when ? new Date(`${when.slice(0, 10)}T00:00:00Z`).getTime() > Date.now() : false;

  if (article.page_status === 'published') {
    return when ? `Published · ${relativeDay(when)}` : 'Published · no date';
  }
  if (article.page_status === 'submitted_for_review') return 'Pending review';
  if (!when) return 'Draft · undated';
  return ahead ? `Draft · publishes ${relativeDay(when)}` : `Draft · dated ${relativeDay(when)}`;
}

interface Props {
  article: ArticleRead;
  busy: boolean;
  /** id of a <datalist> of existing category names, offered while typing. */
  suggestionsId?: string;
  onSave: (id: number, category: string, publishedAt: string | null) => void;
  onDetach: (id: number) => void;
  onPublish: (article: ArticleRead) => Promise<unknown>;
}

/** One article as a card row: title carries the weight, metadata sits quiet
 *  underneath, and the actions live on the row rather than behind a menu.
 *
 *  Category and date edit in place. Opening a whole editor to change a chip is
 *  the thing this list exists to avoid — the body is edited in pagebuilder, so
 *  if these two fields also needed a round trip the list would have no job.
 */
export function ArticleRow({ article, busy, suggestionsId, onSave, onDetach, onPublish }: Props) {
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(article.category);
  const [date, setDate] = useState(toDateInput(article.published_at));

  const dirty = category !== article.category || date !== toDateInput(article.published_at);
  const isDraft = article.page_status === 'draft';
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

        <p className="mt-1 text-xs text-muted-foreground">{statusLine(article)}</p>
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
            {article.page_status === 'published' && (
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

        <ConfirmDialog
          // Low: the page and its body survive; only the news metadata goes.
          level="low"
          title={`Detach "${article.title}"?`}
          description="The page and its body stay. Only the category and date attached to it are removed, and it stops appearing in news feeds."
          confirmLabel="Detach"
          onConfirm={async () => onDetach(article.id)}
          trigger={
            <Button type="button" size="sm" variant="ghost" disabled={busy}>
              Detach
            </Button>
          }
        />
      </div>
    </li>
  );
}
