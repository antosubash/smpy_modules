import { Head, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  type ArticleRead,
  formatArticleDate,
  listArticles,
  purgeArticle,
  restoreArticle,
} from '../utils/api';
import { keys, useT } from '../utils/i18n';

/** Binned articles, and the two things you can do with them.
 *
 * Trash, restore and purge were implemented and tested from the day the module
 * owned its own content, and had no screen. So the admin list offered a hard
 * delete instead — the one action the soft delete exists to avoid — and a
 * trashed article was reachable only over the API.
 *
 * A trashed article keeps its slug claimed, which is why this screen matters
 * beyond recovery: an author who bins an article and cannot find it will simply
 * try to recreate it, and be told the URL is taken by something they cannot
 * see.
 */
export default function Trash() {
  const { t } = useT();
  const copy = keys.news.trash;
  const { auth } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
  // Purge needs `news.publish` on the backend, the same pair a hard delete
  // needs — see ArticleRow and ArticleEditor. Restore does not: it is
  // `news.edit` alone, so it stays available below with no gate of its own.
  const canPublish = auth?.permissions?.includes('news.publish') ?? false;

  const [items, setItems] = useState<ArticleRead[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) =>
      listArticles({ trashed: true, limit: 100, signal })
        .then((response) => setItems(response.items))
        .catch((e: Error) => {
          if (signal?.aborted) return;
          toast.error(e.message);
          setItems([]);
        }),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const act = async (id: number, action: () => Promise<unknown>, done: string) => {
    setBusyId(id);
    try {
      await action();
      await load();
      toast.success(done);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageShell
      title={t(copy.title)}
      description={t(copy.description)}
      actions={
        <Button variant="outline" onClick={() => router.visit('/admin/news/')}>
          {t(copy.back_to_list)}
        </Button>
      }
    >
      <Head title={t(copy.title)} />

      {items === null ? (
        <div role="status" aria-label={t(copy.loading)} className="h-24" />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(copy.empty)}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((article) => (
            <li
              key={article.id}
              data-testid="trashed-row"
              data-slug={article.slug}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">{article.title}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {article.url}
                  {article.published_at ? ` · ${formatArticleDate(article.published_at)}` : ''}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyId === article.id}
                  onClick={() =>
                    void act(article.id, () => restoreArticle(article.id), t(copy.restored_toast))
                  }
                >
                  {t(copy.restore)}
                </Button>
                {canPublish && (
                  <ConfirmDialog
                    // High: purging is the one action here with no way back, and
                    // it also frees the slug — so a link already in the world
                    // stops resolving and can later point at something else.
                    level="high"
                    title={t(copy.purge_title, { title: article.title })}
                    description={t(copy.purge_description)}
                    confirmLabel={t(copy.purge_confirm)}
                    onConfirm={() =>
                      act(article.id, () => purgeArticle(article.id), t(copy.purged_toast))
                    }
                    trigger={
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive"
                        disabled={busyId === article.id}
                      >
                        {t(copy.purge_confirm)}
                      </Button>
                    }
                  />
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}

Trash.layout = [AuthenticatedLayout];
