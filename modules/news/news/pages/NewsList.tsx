import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
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
import { useCallback, useEffect, useState } from 'react';

import { ArticleRow } from '../components/ArticleRow';
import { NewArticleDialog } from '../components/NewArticleDialog';
import {
  type ArticleRead,
  detachArticle,
  listArticles,
  listCategories,
  updateArticle,
} from '../utils/api';

const PAGE_SIZE = 100;
const CATEGORY_SUGGESTIONS_ID = 'news-category-suggestions';

export default function NewsList() {
  const { auth } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
  const canEdit = auth?.permissions?.includes('news.edit');

  const [articles, setArticles] = useState<ArticleRead[] | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listArticles({ limit: PAGE_SIZE })
      .then((response) => setArticles(response.items))
      .catch((e) => setError((e as Error).message));
    // Suggestions only — a failure here just means no autocompletion, which
    // is not worth an error banner over a perfectly usable list.
    listCategories()
      .then((response) => setCategories(response.items.map((c) => c.category)))
      .catch(() => setCategories([]));
  }, []);

  useEffect(refresh, [refresh]);

  // Busy is per row, so saving one article does not lock every other row's
  // inputs while the request is in flight.
  const runRow = async (id: number, work: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await work();
      refresh();
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

      {articles === null ? (
        <div role="status" aria-label="Loading articles" className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : articles.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No articles yet. "New article" creates a page and opens it in the editor.
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

      <datalist id={CATEGORY_SUGGESTIONS_ID}>
        {categories.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </PageShell>
  );
}

NewsList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
