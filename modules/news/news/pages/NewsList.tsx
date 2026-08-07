import { Head, usePage } from '@inertiajs/react';
import { FilterPills } from '@simple-module-py/ui/components/FilterPills';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ArticleRow } from '../components/ArticleRow';
import { NewArticleDialog } from '../components/NewArticleDialog';
import {
  type ArticleRead,
  type CategoryCount,
  detachArticle,
  listArticles,
  listCategories,
  updateArticle,
} from '../utils/api';

const PAGE_SIZE = 25;
const CATEGORY_SUGGESTIONS_ID = 'news-category-suggestions';

export default function NewsList() {
  const { auth } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
  const canEdit = auth?.permissions?.includes('news.edit');

  const [articles, setArticles] = useState<ArticleRead[] | null>(null);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [category, setCategory] = useState('');

  // Only the newest refresh may write state. An AbortSignal alone does not
  // cover this: `runRow` refreshes without one, so a save's re-fetch could
  // still land after a page change and paint the old page's rows under the new
  // pager, with nothing left to re-fetch and correct it. The signal still
  // earns its place — it cancels the request the effect is walking away from.
  const latestRequest = useRef(0);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++latestRequest.current;
      const superseded = () => request !== latestRequest.current;

      // Undated first: an undated article is work in progress — with the
      // default (public-feed) order it would sit on the last page, burying
      // exactly the row its author just created.
      const articlesLoaded = listArticles({
        limit: PAGE_SIZE,
        offset,
        category: category || undefined,
        undated_first: true,
        signal,
      })
        .then((response) => {
          if (superseded()) return;
          // A load that worked clears a banner left by one that did not;
          // otherwise a transient failure sticks around until the next write.
          setError(null);
          // Detaching the last row of the last page leaves the offset past the
          // end. Step back and let the re-fetch fill the list; writing the
          // empty response first would flash the "no articles yet" box over a
          // list that still holds a full page.
          if (response.items.length === 0 && offset > 0) {
            setOffset(Math.max(0, offset - PAGE_SIZE));
            return;
          }
          setArticles(response.items);
          setTotal(response.total);
        })
        .catch((e) => {
          if (superseded() || signal?.aborted) return;
          setError((e as Error).message);
        });

      // Pills and suggestions only — a failure here just means no filter row,
      // which is not worth an error banner over a perfectly usable list.
      const categoriesLoaded = listCategories(signal)
        .then((response) => {
          if (superseded()) return;
          setCategories(response.items);
          // Editing the last row out of the filtered category empties the
          // filter; fall back to All rather than pinning an orphaned pill.
          if (category && !response.items.some((c) => c.category === category)) {
            setCategory('');
            setOffset(0);
          }
        })
        .catch(() => {
          // Deliberately keep the last known list: emptying it unmounts the
          // pill row, which would strand an active filter with no control
          // left to clear it.
        });

      await Promise.all([articlesLoaded, categoriesLoaded]);
    },
    [offset, category],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  // Busy is per row, so saving one article does not lock every other row's
  // inputs while the request is in flight.
  const runRow = async (id: number, work: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await work();
      // Awaited: clearing busy before the new rows land re-enables a row that
      // is about to disappear, and a second Detach on it answers 404.
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageShell
      title="News"
      description="Articles are page-builder pages. Edit the body in the page editor; set the category and date here."
      actions={canEdit ? <NewArticleDialog /> : undefined}
    >
      <Head title="News" />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {categories.length > 0 && (
        <FilterPills
          className="mb-4"
          value={category}
          onChange={(next) => {
            setCategory(next);
            setOffset(0);
          }}
          options={[
            { value: '', label: 'All' },
            ...categories.map((c) => ({
              value: c.category,
              label: `${c.category} (${c.count})`,
            })),
          ]}
        />
      )}

      {articles === null ? (
        <div role="status" aria-label="Loading articles" className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : articles.length === 0 && offset === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          {category ? (
            // An active filter is the likelier reason for an empty list, and
            // saying "no articles yet" here is simply false. The button also
            // covers the case where the pill row is gone because the category
            // request failed — otherwise the filter cannot be cleared at all.
            <>
              No articles in "{category}".{' '}
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                onClick={() => {
                  setCategory('');
                  setOffset(0);
                }}
              >
                Show all articles
              </Button>
            </>
          ) : (
            'No articles yet. "New article" creates a page and opens it in the editor.'
          )}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Article</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Date</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {articles.map((article) => (
              <ArticleRow
                // Keyed on the server state, not just the id: ArticleRow holds
                // the inputs' values in local state seeded from its props, so
                // a row reused across a refresh would keep showing what the
                // author typed rather than what was saved.
                key={`${article.id}:${article.category}:${article.published_at ?? ''}`}
                article={article}
                busy={busyId === article.id || !canEdit}
                suggestionsId={CATEGORY_SUGGESTIONS_ID}
                onSave={(id, category, publishedAt) =>
                  runRow(id, () => updateArticle(id, { category, published_at: publishedAt }))
                }
                onDetach={(id) => runRow(id, () => detachArticle(id))}
              />
            ))}
          </TableBody>
        </Table>
      )}

      {articles !== null && total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {Math.min(offset + 1, total)}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="space-x-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
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
