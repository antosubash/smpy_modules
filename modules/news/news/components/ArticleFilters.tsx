import { Input } from '@simple-module-py/ui/components/ui/input';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import type { ArticleCounts, CategoryCount } from '../utils/api';
import { localeLabel } from '../utils/locale';

const SEARCH_INPUT_ID = 'news-article-search';
const CATEGORY_SELECT_ID = 'news-article-category';
const LOCALE_SELECT_ID = 'news-article-locale';

/** The pipeline is two-state — draft or published. `undated` is not a third
 *  state: it cuts across both, and it is the work-in-progress pile a writer
 *  actually wants to find. */
const STATUSES = [
  { value: '', label: 'All', count: (c: ArticleCounts) => c.all },
  { value: 'draft', label: 'Draft', count: (c: ArticleCounts) => c.draft },
  { value: 'published', label: 'Published', count: (c: ArticleCounts) => c.published },
  { value: 'undated', label: 'Undated', count: (c: ArticleCounts) => c.undated },
];

interface Props {
  q: string;
  status: string;
  category: string;
  locale: string;
  counts: ArticleCounts;
  categories: CategoryCount[];
  /** Every language the site publishes in. One or none hides the select — a
   *  filter that cannot narrow anything is furniture. */
  locales: string[];
  onChange: (next: { q?: string; status?: string; category?: string; locale?: string }) => void;
}

/** Search, status pills and the category select, above the list.
 *
 * Counts sit on the pills rather than in a summary line so the cost of
 * switching filter is visible before the click — "Draft 6" answers the question
 * the click was going to ask.
 */
export function ArticleFilters({
  q,
  status,
  category,
  locale,
  counts,
  categories,
  locales,
  onChange,
}: Props) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Input
        id={SEARCH_INPUT_ID}
        aria-label="Search headline or slug"
        placeholder="Search headline or slug"
        value={q}
        className="h-9 w-64"
        onChange={(e) => onChange({ q: e.target.value })}
      />

      {/* A real fieldset rather than role="group": the pills are a single
          choice among four, and the legend names that choice for a screen
          reader without taking space in the layout. */}
      <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0">
        <legend className="sr-only">Filter by status</legend>
        {STATUSES.map((option) => {
          const active = status === option.value;
          return (
            <button
              key={option.value || 'all'}
              type="button"
              aria-pressed={active}
              data-testid="status-pill"
              onClick={() => onChange({ status: option.value })}
              className={`rounded-full border px-3 py-1 text-sm transition ${
                active ? 'border-primary bg-primary/10 font-medium' : 'bg-card hover:bg-muted'
              }`}
            >
              {option.label}{' '}
              <span className="tabular-nums text-muted-foreground">{option.count(counts)}</span>
            </button>
          );
        })}
      </fieldset>

      {categories.length > 0 && (
        <NativeSelect
          id={CATEGORY_SELECT_ID}
          aria-label="Filter by category"
          value={category}
          className="h-9 w-48"
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.category} value={c.category}>
              {c.category} ({c.count})
            </option>
          ))}
        </NativeSelect>
      )}

      {locales.length > 1 && (
        <NativeSelect
          id={LOCALE_SELECT_ID}
          aria-label="Filter by language"
          value={locale}
          className="h-9 w-44"
          onChange={(e) => onChange({ locale: e.target.value })}
        >
          <option value="">All languages</option>
          {locales.map((tag) => (
            <option key={tag} value={tag}>
              {localeLabel(tag)}
            </option>
          ))}
        </NativeSelect>
      )}
    </div>
  );
}
