import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect, useRef } from 'react';

import { SearchSection } from '../components/search/SearchSection';
import { useAdminSearch } from '../hooks/useAdminSearch';
import { keys, useT } from '../utils/i18n';

const SEARCH_INPUT_ID = 'admin-search-input';

/** Search across articles, pages and media.
 *
 * One screen rather than three, because the question people arrive with is
 * "where is the thing about canopy" — not "is the thing about canopy a page or
 * an asset". The sections keep the answer legible once it arrives.
 */
export default function Search() {
  const { t } = useT();
  const copy = keys.news.search;
  const { q, setQuery, results, loading, error, section, setSection } = useAdminSearch();
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus on arrival: this screen exists to be typed into, and arriving on it
  // with the cursor elsewhere wastes the click that got you here.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const counts = results && {
    all: results.article_total + results.page_total + results.media_total,
    articles: results.article_total,
    pages: results.page_total,
    media: results.media_total,
  };

  const filters = [
    { key: '', label: t(copy.filter_all), count: counts?.all },
    { key: 'articles', label: t(copy.filter_articles), count: counts?.articles },
    { key: 'pages', label: t(copy.filter_pages), count: counts?.pages },
    { key: 'media', label: t(copy.filter_media), count: counts?.media },
  ];

  const show = (key: string) => section === '' || section === key;

  return (
    <PageShell title={t(copy.title)} description={t(copy.description)}>
      <Head title={t(copy.title)} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input
          id={SEARCH_INPUT_ID}
          ref={inputRef}
          aria-label={t(copy.input_label)}
          placeholder={t(copy.input_label)}
          value={q}
          className="h-10 w-80"
          onChange={(e) => setQuery(e.target.value)}
        />
        {results && (
          <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0">
            <legend className="sr-only">{t(copy.section_legend)}</legend>
            {filters.map((filter) => (
              <button
                key={filter.key || 'all'}
                type="button"
                aria-pressed={section === filter.key}
                data-testid="search-filter"
                onClick={() => setSection(filter.key)}
                className={`rounded-full border px-3 py-1 text-sm transition ${
                  section === filter.key
                    ? 'border-primary bg-primary/10 font-medium'
                    : 'bg-card hover:bg-muted'
                }`}
              >
                {filter.label}{' '}
                <span className="tabular-nums text-muted-foreground">{filter.count ?? 0}</span>
              </button>
            ))}
          </fieldset>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {!q.trim() ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t(copy.prompt_title)}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t(copy.prompt_description)}</p>
        </div>
      ) : loading && !results ? (
        <div role="status" aria-label={t(copy.searching)} className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : results && counts && counts.all === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t(copy.no_match_title, { query: q.trim() })}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t(copy.no_match_description)}</p>
        </div>
      ) : results ? (
        <div className="space-y-8">
          {show('articles') && (
            <SearchSection
              label={t(copy.filter_articles)}
              hits={results.articles}
              total={results.article_total}
              moreHref={`/admin/news/?q=${encodeURIComponent(q.trim())}`}
              moreKey={copy.more_articles}
            />
          )}
          {show('pages') && (
            <SearchSection
              label={t(copy.filter_pages)}
              hits={results.pages}
              total={results.page_total}
              moreHref={results.pages_more_url}
              moreKey={copy.more_pages}
            />
          )}
          {show('media') && (
            <SearchSection
              label={t(copy.filter_media)}
              hits={results.media}
              total={results.media_total}
              moreHref={results.media_more_url}
              moreKey={copy.more_media}
            />
          )}
        </div>
      ) : null}
    </PageShell>
  );
}

Search.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
