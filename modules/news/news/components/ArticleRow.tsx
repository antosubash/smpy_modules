import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@simple-module-py/ui/components/ui/dropdown-menu';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';
import { type ArticleRead, formatArticleDate } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { ArticleRowDelete } from './ArticleRowDelete';
import { statusLine, toDateInput } from './articleStatus';

/** The article editor — category, tags, date, byline and feed behaviour. The
 *  body has a canvas of its own, so it is edited one link further in. */
const articleSettingsUrl = (id: number) => `/admin/news/articles/${id}/edit`;

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
  onDelete: (id: number) => Promise<unknown>;
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
  const { t } = useT();
  const row = keys.news.row;
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(article.category);
  const [date, setDate] = useState(toDateInput(article.published_at));

  const dirty = category !== article.category || date !== toDateInput(article.published_at);
  const isDraft = article.status === 'draft';
  const dateLabel = formatArticleDate(article.published_at) || t(row.no_date);

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
          {t(row.no_image)}
        </div>
      )}

      <div className="min-w-0 flex-1">
        <a
          href={articleSettingsUrl(article.id)}
          className="font-medium hover:underline"
          data-testid="article-title"
        >
          {article.title || t(row.untitled)}
        </a>

        {editing ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Input
              aria-label={t(row.category_input, { title: article.title })}
              value={category}
              disabled={busy}
              list={suggestionsId}
              placeholder={t(row.uncategorised)}
              onChange={(e) => setCategory(e.target.value)}
              className="h-8 w-44"
            />
            <Input
              type="date"
              aria-label={t(row.date_input, { title: article.title })}
              value={date}
              disabled={busy}
              onChange={(e) => setDate(e.target.value)}
              className="h-8 w-40"
            />
            <Button type="button" size="sm" disabled={busy || !dirty} onClick={save}>
              {t(row.save)}
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
              {t(row.cancel)}
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
              aria-label={t(row.edit_category_and_date, {
                value: article.category || t(row.uncategorised),
              })}
              className="rounded-full border px-2 py-0.5 text-xs hover:bg-muted"
            >
              {article.category || t(row.uncategorised)}
            </button>
            <span>·</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(true)}
              aria-label={t(row.edit_category_and_date, { value: dateLabel })}
              className="hover:underline"
            >
              {dateLabel}
            </button>
            <span>·</span>
            <span className="truncate">{article.url}</span>
          </div>
        )}

        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{statusLine(article, t)}</span>
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
              {t(row.unpublished_edits)}
            </span>
          )}
        </p>
      </div>

      <div className="flex w-full shrink-0 items-center justify-end gap-1 sm:w-auto">
        <Button type="button" size="sm" variant="outline" asChild>
          <a href={articleSettingsUrl(article.id)}>{t(row.edit)}</a>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              aria-label={t(row.more_actions, { title: article.title })}
            >
              ···
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {isDraft && (
              <DropdownMenuItem onSelect={() => void onPublish(article).catch(() => {})}>
                {t(row.publish_now)}
              </DropdownMenuItem>
            )}
            {article.status === 'published' && (
              <DropdownMenuItem asChild>
                <a href={article.url} target="_blank" rel="noopener noreferrer">
                  {t(row.view_on_site)}
                </a>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <a href={article.edit_url}>{t(row.edit_body)}</a>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setEditing(true)}>
              {t(row.edit_category_date_action)}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <ArticleRowDelete
          article={article}
          busy={busy}
          canPublish={canPublish}
          onDelete={onDelete}
          onTrash={onTrash}
        />
      </div>
    </li>
  );
}
