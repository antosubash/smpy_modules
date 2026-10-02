import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import type { ArticleRead } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
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
  const { t } = useT();
  const copy = keys.news.inspector;
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
        <Label htmlFor={TITLE_ID}>{t(copy.headline_label)}</Label>
        <Input
          id={TITLE_ID}
          value={draft.title}
          disabled={busy}
          onChange={(e) => onChange({ title: e.target.value })}
        />
        {!draft.title.trim() && (
          <p className="text-xs text-destructive">{t(copy.headline_required)}</p>
        )}
      </div>

      <div className="grid gap-2">
        <Label htmlFor={SLUG_ID}>{t(copy.url_label)}</Label>
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
          <p className="text-xs text-destructive">{t(copy.slug_invalid)}</p>
        ) : (
          <p className="text-xs text-muted-foreground">{t(copy.slug_help)}</p>
        )}
      </div>

      <div className="grid gap-2">
        <Label htmlFor={CATEGORY_ID}>{t(copy.category_label)}</Label>
        <NativeSelect
          id={CATEGORY_ID}
          value={draft.category}
          disabled={busy}
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">{t(copy.category_none)}</option>
          {categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="news-article-tags">{t(copy.tags_label)}</Label>
        <TagInput
          tags={draft.tags}
          disabled={busy}
          suggestions={tagSuggestions}
          onChange={(tags) => onChange({ tags })}
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="grid gap-2">
          <Label htmlFor={DATE_ID}>{t(copy.date_label)}</Label>
          <Input
            id={DATE_ID}
            type="date"
            value={draft.date}
            disabled={busy}
            onChange={(e) => onChange({ date: e.target.value })}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={TIME_ID}>{t(copy.time_label)}</Label>
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
            t(copy.date_help_future)
          : t(copy.date_help_past)}
      </p>

      <div className="grid gap-2">
        <Label htmlFor={AUTHOR_ID}>{t(copy.author_label)}</Label>
        <Input
          id={AUTHOR_ID}
          value={draft.author}
          disabled={busy}
          placeholder={t(copy.author_placeholder)}
          onChange={(e) => onChange({ author: e.target.value })}
        />
      </div>

      <fieldset className="m-0 grid gap-3 border-0 p-0">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t(copy.feed_legend)}
        </legend>

        <div className="flex items-start gap-2">
          <Checkbox
            id={PIN_ID}
            checked={draft.pinned}
            disabled={busy}
            onCheckedChange={(checked) => onChange({ pinned: checked === true })}
          />
          <div className="grid gap-0.5">
            <Label htmlFor={PIN_ID}>{t(copy.pin_label)}</Label>
            <p className="text-xs text-muted-foreground">{t(copy.pin_help)}</p>
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
            <Label htmlFor={FEED_ID}>{t(copy.feed_label)}</Label>
            <p className="text-xs text-muted-foreground">{t(copy.feed_help)}</p>
          </div>
        </div>
      </fieldset>
    </div>
  );
}
