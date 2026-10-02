import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import type { ArticleRead } from '../../utils/api';
import { SLUG_PATTERN } from '../../utils/slugify';
import type { CategoryRead } from '../../utils/taxonomyApi';
import { TagInput } from './TagInput';

const TITLE_ID = 'article-title';
const SLUG_ID = 'article-slug';
const CATEGORY_ID = 'article-category';
const DATE_ID = 'article-date';
const TIME_ID = 'article-time';
const AUTHOR_ID = 'article-author';
const PIN_ID = 'article-pinned';
const FEED_ID = 'article-show-in-feed';

/** A draft of the fields this panel edits. Held by the page so a save sends
 *  one request rather than one per control. */
export interface ArticleDraft {
  title: string;
  slug: string;
  category: string;
  tags: string[];
  date: string;
  time: string;
  author: string;
  pinned: boolean;
  showInFeed: boolean;
}

interface Props {
  article: ArticleRead;
  draft: ArticleDraft;
  categories: CategoryRead[];
  tagSuggestions: string[];
  busy: boolean;
  onChange: (patch: Partial<ArticleDraft>) => void;
}

/** Everything about an article except the blocks its body is made of.
 *
 * The headline and the URL are edited here. They used to belong to the page an
 * article was attached to, so this panel showed the address read-only and told
 * the author to change it "in the page editor" — advice that outlived the
 * screen it pointed at and left an article unrenameable anywhere in the
 * console. They are columns on `news_articles` now, and this is the screen that
 * owns them.
 *
 * The date and time are two controls over one stored instant rather than a
 * single datetime field, because they are decided at different moments: the
 * date is editorial and set early, the time only matters when the article is
 * scheduled, and merging them makes the common case (a date, no particular
 * time) require thinking about both.
 */
export function ArticleInspector({
  article,
  draft,
  categories,
  tagSuggestions,
  busy,
  onChange,
}: Props) {
  const future = draft.date
    ? new Date(`${draft.date}T${draft.time || '00:00'}`) > new Date()
    : false;

  // `url` is the public prefix plus the stored slug, so removing the stored
  // slug leaves the prefix. Taken from the server's answer rather than from a
  // setting read here, because the prefix is configurable and this screen
  // should show the address the article actually has.
  const prefix = article.url.slice(0, article.url.length - article.slug.length);

  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        <Label htmlFor={TITLE_ID}>Headline</Label>
        <Input
          id={TITLE_ID}
          value={draft.title}
          disabled={busy}
          onChange={(e) => onChange({ title: e.target.value })}
        />
        {!draft.title.trim() && (
          <p className="text-xs text-destructive">An article needs a headline.</p>
        )}
      </div>

      <div className="grid gap-2">
        <Label htmlFor={SLUG_ID}>URL</Label>
        <div className="flex items-center gap-1">
          <span className="shrink-0 text-sm text-muted-foreground">{prefix}</span>
          <Input
            id={SLUG_ID}
            value={draft.slug}
            disabled={busy}
            onChange={(e) => onChange({ slug: e.target.value })}
          />
        </div>
        {draft.slug && !SLUG_PATTERN.test(draft.slug) ? (
          <p className="text-xs text-destructive">
            Lowercase letters, numbers and hyphens, starting with a letter or number.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Changing this moves the article. The old address keeps working — a rename records a
            redirect, because it is already in bookmarks and in a search index that has not
            recrawled.
          </p>
        )}
      </div>

      <div className="grid gap-2">
        <Label htmlFor={CATEGORY_ID}>Category</Label>
        <NativeSelect
          id={CATEGORY_ID}
          value={draft.category}
          disabled={busy}
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">Uncategorised</option>
          {categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="news-article-tags">Tags</Label>
        <TagInput
          tags={draft.tags}
          disabled={busy}
          suggestions={tagSuggestions}
          onChange={(tags) => onChange({ tags })}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="grid gap-2">
          <Label htmlFor={DATE_ID}>Display date</Label>
          <Input
            id={DATE_ID}
            type="date"
            value={draft.date}
            disabled={busy}
            onChange={(e) => onChange({ date: e.target.value })}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={TIME_ID}>Time</Label>
          <Input
            id={TIME_ID}
            type="time"
            value={draft.time}
            disabled={busy || !draft.date}
            onChange={(e) => onChange({ time: e.target.value })}
          />
        </div>
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">
        {future
          ? // It used to say "lists this as scheduled", which read as a promise
            // the module could not keep — nothing acted on the date. Real
            // scheduling is the Go-live control below; this one is editorial.
            'The date shown to readers. It does not publish anything — use Go live for that.'
          : 'Clearing the date makes this undated work in progress, which sorts to the top of the list.'}
      </p>

      <div className="grid gap-2">
        <Label htmlFor={AUTHOR_ID}>Author</Label>
        <Input
          id={AUTHOR_ID}
          value={draft.author}
          disabled={busy}
          placeholder="Byline"
          onChange={(e) => onChange({ author: e.target.value })}
        />
      </div>

      <fieldset className="m-0 grid gap-3 border-0 p-0">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Feed behaviour
        </legend>

        <div className="flex items-start gap-2">
          <Checkbox
            id={PIN_ID}
            checked={draft.pinned}
            disabled={busy}
            onCheckedChange={(checked) => onChange({ pinned: checked === true })}
          />
          <div className="grid gap-0.5">
            <Label htmlFor={PIN_ID}>Pin to the top of listings</Label>
            <p className="text-xs text-muted-foreground">
              Sorts before the date rather than changing it, so the archive still reads correctly
              once it is unpinned.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-2">
          <Checkbox
            id={FEED_ID}
            checked={draft.showInFeed}
            disabled={busy}
            onCheckedChange={(checked) => onChange({ showInFeed: checked === true })}
          />
          <div className="grid gap-0.5">
            <Label htmlFor={FEED_ID}>Show in feed blocks</Label>
            <p className="text-xs text-muted-foreground">
              Off keeps the article at its own URL and out of the chronological feed.
            </p>
          </div>
        </div>
      </fieldset>
    </div>
  );
}
