/** The search box on the public archive.
 *
 * A plain GET `<form>` rather than an input wired to client state, and that is
 * the whole design. Submitting navigates to `{base_path}?q=…`, so a search is
 * an address: it can be linked, bookmarked, reloaded and paged, and the pager
 * on the results carries the term because it is in the URL the pager builds
 * from. Client-side filtering would have given a reader a screen they could not
 * send to anyone — the same reason the archive pages with real links instead of
 * a "load more" button.
 *
 * The form's `action` is the archive page it sits on, so a search typed on a
 * category page searches that category. It deliberately carries no `page`
 * field: a new search starts at the beginning, and keeping the old page number
 * would land the reader past the end of a shorter list.
 *
 * In `components/`, not `pages/`. Every file under a module's `pages`
 * directory is registered as an Inertia page by `import.meta.glob`, and a
 * search box is not a screen.
 */

import { keys, useT } from '../utils/i18n';

interface Props {
  /** Where the search goes — this archive's own path, without a query string. */
  basePath: string;
  /** The term already searched for, echoed back so the box shows what produced
   *  the page rather than emptying itself on every reload. */
  query: string;
  /** Whether this archive is already narrowed to a category, tag or byline.
   *  Changes what the box says it will search, because "Search articles" on a
   *  page that only searches one category is a small lie. */
  narrowed: boolean;
  /** What this archive calls itself, for the narrowed placeholder. */
  heading: string;
}

export function ArchiveSearch({ basePath, query, narrowed, heading }: Props) {
  const { t } = useT();
  const placeholder = narrowed
    ? t(keys.news.public.search_placeholder_narrowed, { heading })
    : t(keys.news.public.search_placeholder);
  return (
    // `<search>` rather than `role="search"` on the form: the element carries
    // the role, and one landmark is what a screen-reader user skips to.
    <search className="mb-10 block">
      <form method="get" action={basePath} className="flex gap-2">
        <label htmlFor="archive-search" className="sr-only">
          {placeholder}
        </label>
        <input
          id="archive-search"
          type="search"
          name="q"
          defaultValue={query}
          placeholder={placeholder}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted"
        >
          {t(keys.news.public.search_submit)}
        </button>
      </form>
    </search>
  );
}
