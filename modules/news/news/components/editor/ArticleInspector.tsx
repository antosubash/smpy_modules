import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import type { ArticleRead } from '../../utils/api';
import type { CategoryRead } from '../../utils/taxonomyApi';
import { TagInput } from './TagInput';

const CATEGORY_ID = 'article-category';
const DATE_ID = 'article-date';
const TIME_ID = 'article-time';
const AUTHOR_ID = 'article-author';
const PIN_ID = 'article-pinned';
const FEED_ID = 'article-show-in-feed';

/** A draft of the fields this panel edits. Held by the page so a save sends
 *  one request rather than one per control. */
export interface ArticleDraft {
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

/** The Article tab — everything the page underneath has no concept of.
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

  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        <Label htmlFor="article-url">URL</Label>
        <p id="article-url" className="break-all font-mono text-sm text-muted-foreground">
          {article.url}
        </p>
        <p className="text-xs text-muted-foreground">
          The slug lives with the page. Change it in the page editor — it is the article's public
          address, so nothing else may move it.
        </p>
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
          <Label htmlFor={DATE_ID}>Publish date</Label>
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
          ? 'A future date lists this as scheduled. It stays a draft until you publish it.'
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
            <Label htmlFor={PIN_ID}>Pin to top of /news</Label>
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
