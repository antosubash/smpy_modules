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
import { deleteArticle, publishArticle, trashArticle, updateArticle } from '../utils/api';
import { keys, useT } from '../utils/i18n';

const CATEGORY_SUGGESTIONS_ID = 'news-category-suggestions';

/** The whole empty-state sentence per status, in each of its two endings.
 *
 *  A sentence rather than a noun spliced into one: "No drafts match" and "No
 *  published articles match" differ by more than a word in a language that
 *  declines the noun after a negation, and a catalogue holding only the noun
 *  gives a translator nowhere to say so.
 */
const NO_MATCH: Record<string, { query: string; filter: string }> = {
  '': {
    query: keys.news.list.no_match_articles_query,
    filter: keys.news.list.no_match_articles_filter,
  },
  draft: {
    query: keys.news.list.no_match_drafts_query,
    filter: keys.news.list.no_match_drafts_filter,
  },
  published: {
    query: keys.news.list.no_match_published_query,
    filter: keys.news.list.no_match_published_filter,
  },
  undated: {
    query: keys.news.list.no_match_undated_query,
    filter: keys.news.list.no_match_undated_filter,
  },
};

/** The article list: search, status filters, and card rows.
 *
 * Rows are cards rather than table cells because the metadata is a sentence
 * about state ("Draft · dated Feb 15"), not a set of comparable columns — a
 * table would line up four values nobody scans vertically.
 */
interface LocaleProps {
  /** Every language the site publishes in, and the one that serves at the
   *  unprefixed public URL. Server-rendered so the filter and the New article
   *  dialog offer exactly what the API will accept. */
  locales?: string[];
  default_locale?: string;
}

export default function NewsList() {
  const { t } = useT();
  const props = usePage<{ props: SharedProps & LocaleProps }>().props as unknown as SharedProps &
    LocaleProps;
  const { auth } = props;
  const canEdit = auth?.permissions?.includes('news.edit');
  // Hard delete needs `news.publish` too — see `ArticleRow`. Without it a
  // row offers the recoverable trash instead.
  const canPublish = auth?.permissions?.includes('news.publish') ?? false;
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
  const noMatch = NO_MATCH[filters.status] ?? NO_MATCH[''];

  return (
    <PageShell
      title={t(keys.news.list.title)}
      description={t(keys.news.list.description, {
        published: counts.published,
        draft: counts.draft,
      })}
      actions={
        canEdit ? <NewArticleDialog locales={locales} defaultLocale={defaultLocale} /> : undefined
      }
    >
      <Head title={t(keys.news.list.title)} />
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
        <div role="status" aria-label={t(keys.news.list.loading)} className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : articles.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          {filtered ? (
            <>
              <p className="font-medium">
                {filters.q ? t(noMatch.query, { query: filters.q }) : t(noMatch.filter)}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {/* Say what a wider filter would find. "No results" alone
                    leaves the reader guessing whether the search or the
                    status pill is the thing that is too narrow. */}
                {counts.all > 0
                  ? t(keys.news.list.across_statuses, { count: counts.all })
                  : t(keys.news.list.nothing_in_archive)}
              </p>
              <div className="mt-3 flex justify-center gap-2">
                {filters.status && counts.all > 0 && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setFilters({ status: '', offset: 0 })}
                  >
                    {t(keys.news.list.search_all_statuses)}
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setFilters({ q: '', status: '', category: '', offset: 0 })}
                >
                  {t(keys.news.list.clear)}
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="font-medium">{t(keys.news.list.empty_title)}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {t(keys.news.list.empty_description)}
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
              canPublish={canPublish}
              onSave={(id, category, publishedAt) =>
                runRow(id, () => updateArticle(id, { category, published_at: publishedAt }))
              }
              onDelete={(id) => runRow(id, () => deleteArticle(id))}
              onTrash={(id) => runRow(id, () => trashArticle(id))}
              onPublish={(target) => runRow(target.id, () => publishArticle(target.id))}
            />
          ))}
        </ul>
      )}

      {articles !== null && articles.length > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>{t(keys.news.list.showing, { shown, total })}</span>
          {shown < total && (
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={loadMore}>
              {t(keys.news.list.load_more)}
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

NewsList.layout = [AuthenticatedLayout];
