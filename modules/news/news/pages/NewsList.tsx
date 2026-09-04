import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useEffect } from 'react';

import { ArticleFilters } from '../components/ArticleFilters';
import { ArticleRow } from '../components/ArticleRow';
import { NewArticleDialog } from '../components/NewArticleDialog';
import { useArticleList } from '../hooks/useArticleList';
import { detachArticle, publishArticle, updateArticle } from '../utils/api';

const CATEGORY_SUGGESTIONS_ID = 'news-category-suggestions';

/** Plural nouns for the empty state, so it reads "No drafts match" rather than
 *  splicing the raw status value in and producing "No draft match". */
const STATUS_NOUN: Record<string, string> = {
  draft: 'drafts',
  published: 'published articles',
  undated: 'undated articles',
};

/** The article list: search, two-state pipeline filters, and card rows.
 *
 * Rows are cards rather than table cells because the metadata is a sentence
 * about state ("Draft · publishes in 15d"), not a set of comparable columns —
 * a table would line up four values nobody scans vertically.
 */
interface LocaleProps {
  /** Every language the site publishes in, and the one that serves at the
   *  unprefixed public URL. Server-rendered so the filter and the New article
   *  dialog offer exactly what the API will accept. */
  locales?: string[];
  default_locale?: string;
}

export default function NewsList() {
  const props = usePage<{ props: SharedProps & LocaleProps }>().props as unknown as SharedProps &
    LocaleProps;
  const { auth } = props;
  const canEdit = auth?.permissions?.includes('news.edit');
  const locales = props.locales ?? [];
  const defaultLocale = props.default_locale ?? 'en';

  const {
    articles,
    categories,
    counts,
    total,
    shown,
    busy,
    busyId,
    error,
    filters,
    setFilters,
    load,
    loadMore,
    runRow,
  } = useArticleList();

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const filtered = !!(filters.q || filters.status || filters.category || filters.locale);

  return (
    <PageShell
      title="News"
      description={`${counts.published} published · ${counts.draft} drafts · public at /news/:slug`}
      actions={
        canEdit ? <NewArticleDialog locales={locales} defaultLocale={defaultLocale} /> : undefined
      }
    >
      <Head title="News" />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <ArticleFilters
        q={filters.q}
        status={filters.status}
        category={filters.category}
        locale={filters.locale}
        counts={counts}
        categories={categories}
        locales={locales}
        onChange={(next) => setFilters({ ...next, offset: 0 })}
      />

      {articles === null ? (
        <div role="status" aria-label="Loading articles" className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : articles.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          {filtered ? (
            <>
              <p className="font-medium">
                No {STATUS_NOUN[filters.status] ?? 'articles'} match
                {filters.q ? ` “${filters.q}”` : ' this filter'}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {/* Say what a wider filter would find. "No results" alone
                    leaves the reader guessing whether the search or the
                    status pill is the thing that is too narrow. */}
                {counts.all > 0
                  ? `${counts.all} article${counts.all === 1 ? '' : 's'} match across all statuses. Widen the filter or clear the search.`
                  : 'Nothing in the archive matches. Try a shorter search.'}
              </p>
              <div className="mt-3 flex justify-center gap-2">
                {filters.status && counts.all > 0 && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setFilters({ status: '', offset: 0 })}
                  >
                    Search all statuses
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setFilters({ q: '', status: '', category: '', offset: 0 })}
                >
                  Clear
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="font-medium">No articles yet</p>
              <p className="mt-1 text-sm text-muted-foreground">
                “New article” creates a page and opens it in the editor. Set the category and date
                back here afterwards.
              </p>
            </>
          )}
        </div>
      ) : (
        <ul className="space-y-2">
          {articles.map((article) => (
            <ArticleRow
              // Keyed on the server state, not just the id: the row seeds its
              // inputs from its props, so a row reused across a refresh would
              // keep showing what the author typed rather than what was saved.
              key={`${article.id}:${article.category}:${article.published_at ?? ''}`}
              article={article}
              busy={busyId === article.id || busy || !canEdit}
              suggestionsId={CATEGORY_SUGGESTIONS_ID}
              onSave={(id, category, publishedAt) =>
                runRow(id, () => updateArticle(id, { category, published_at: publishedAt }))
              }
              onDetach={(id) => runRow(id, () => detachArticle(id))}
              onPublish={(target) => runRow(target.id, () => publishArticle(target.id))}
            />
          ))}
        </ul>
      )}

      {articles !== null && articles.length > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {shown} of {total}
          </span>
          {shown < total && (
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={loadMore}>
              Load more
            </Button>
          )}
        </div>
      )}

      <datalist id={CATEGORY_SUGGESTIONS_ID}>
        {categories.map((c) => (
          <option key={c.category} value={c.category} />
        ))}
      </datalist>
    </PageShell>
  );
}

NewsList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
