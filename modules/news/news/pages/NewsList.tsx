import { Head, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useCallback, useEffect, useState } from 'react';

import { ArticleRow } from '../components/ArticleRow';
import {
  type ArticleRead,
  attachArticle,
  createArticlePage,
  detachArticle,
  listArticles,
  slugify,
  updateArticle,
} from '../utils/api';

const PAGE_SIZE = 100;

export default function NewsList() {
  const { auth } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
  const canEdit = auth?.permissions?.includes('news.edit');

  const [articles, setArticles] = useState<ArticleRead[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listArticles({ limit: PAGE_SIZE })
      .then((response) => setArticles(response.items))
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(refresh, [refresh]);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleNew = () =>
    run(async () => {
      const title = prompt('Article title');
      if (!title) return;
      // Create the page first: the article row is metadata *about* a page, so
      // there is nothing to attach to until one exists.
      const pageId = await createArticlePage(title, `${slugify(title)}-${Date.now()}`);
      await attachArticle({ page_id: pageId, category: '', published_at: null });
      router.visit(`/pagebuilder/${pageId}`);
    });

  return (
    <PageShell
      title="News"
      description="Articles are page-builder pages. Edit the body in the page editor; set the category and date here."
    >
      <Head title="News" />
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {canEdit && (
        <div className="mb-4">
          <Button type="button" disabled={busy} onClick={handleNew}>
            New article
          </Button>
        </div>
      )}

      {articles === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : articles.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No articles yet. "New article" creates a page and opens it in the editor.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-2 pr-4 font-medium">Article</th>
              <th className="py-2 pr-4 font-medium">Category</th>
              <th className="py-2 pr-4 font-medium">Date</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {articles.map((article) => (
              <ArticleRow
                // Keyed on the server state, not just the id: ArticleRow holds
                // the inputs' values in local state seeded from its props, so
                // a row reused across a refresh would keep showing what the
                // author typed rather than what was saved.
                key={`${article.id}:${article.category}:${article.published_at ?? ''}`}
                article={article}
                busy={busy || !canEdit}
                onSave={(id, category, publishedAt) =>
                  run(() => updateArticle(id, { category, published_at: publishedAt }))
                }
                onDetach={(id) =>
                  run(async () => {
                    if (!confirm('Detach this article? The page and its body stay.')) return;
                    await detachArticle(id);
                  })
                }
              />
            ))}
          </tbody>
        </table>
      )}
    </PageShell>
  );
}

NewsList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
