import { Head, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect } from 'react';
import { ConfirmDialog } from '../components/ConfirmDialog';

import { ArticleInspector } from '../components/editor/ArticleInspector';
import { ScheduleCard } from '../components/editor/ScheduleCard';
import { useArticleEditor } from '../hooks/useArticleEditor';
import { formatArticleDate } from '../utils/api';

/** The article editor — everything about an article except its body.
 *
 * The body used to be a page-builder document, so this screen linked out to
 * that module's canvas. News owns the document now and has a canvas of its own
 * next door; the two stay separate because they are edited in genuinely
 * different postures — a form full of short fields that each save
 * independently, and a full-bleed editor.
 */
export default function ArticleEditor() {
  const page = usePage<{ props: { article_id: number } }>().props as unknown as {
    article_id: number;
    auth?: { permissions?: string[] };
  };
  const { article_id } = page;
  const canPublish = page.auth?.permissions?.includes('news.publish') ?? false;

  const {
    article,
    draft,
    categories,
    tagSuggestions,
    busy,
    dirty,
    valid,
    error,
    saved,
    load,
    patch,
    save,
    publish,
    remove,
  } = useArticleEditor(article_id);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (!article || !draft) {
    return (
      <PageShell title="Article" description="Loading…">
        <Head title="Article" />
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <div role="status" aria-label="Loading article" className="space-y-2">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </PageShell>
    );
  }

  const isDraft = article.status === 'draft';
  const dated = formatArticleDate(article.published_at);
  const status = isDraft
    ? `Draft${dated ? ` · dated ${dated}` : ' · undated'}`
    : `Published${dated ? ` · ${dated}` : ''}`;

  return (
    <PageShell
      title={article.title || 'Untitled article'}
      description={`${article.url} · ${status}`}
      actions={
        <>
          <Button variant="outline" onClick={() => router.visit('/admin/news/')}>
            News / Articles
          </Button>
          {!isDraft && (
            <Button variant="outline" asChild>
              <a href={article.url} target="_blank" rel="noopener noreferrer">
                Preview
              </a>
            </Button>
          )}
          {isDraft && (
            <Button disabled={busy} onClick={() => void publish()}>
              Publish now
            </Button>
          )}
        </>
      }
    >
      <Head title={article.title || 'Article'} />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="space-y-3">
          <div className="rounded-lg border border-dashed p-8 text-center">
            <p className="font-medium">The body has its own canvas</p>
            <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
              Blocks, autosave and revision history live there. This screen owns everything else —
              category, tags, display date, byline and how the article behaves in feeds.
            </p>
            <Button className="mt-3" onClick={() => router.visit(article.edit_url)}>
              Edit the body
            </Button>
          </div>

          <ConfirmDialog
            // Medium, where this used to be low — see ArticleRow for why the
            // same button changed cost when the sidecar went away.
            level="medium"
            title={`Delete “${article.title}”?`}
            description="The article, its body and its tags are removed, and its public URL stops working. This cannot be undone from here."
            confirmLabel="Delete"
            onConfirm={async () => {
              await remove();
              router.visit('/admin/news/');
            }}
            trigger={
              <Button variant="ghost" size="sm" className="text-destructive" disabled={busy}>
                Delete article
              </Button>
            }
          />
        </section>

        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide">Article</h2>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {busy ? 'Saving…' : dirty ? 'Unsaved changes' : saved ? 'Saved' : ''}
            </span>
          </div>

          <ArticleInspector
            article={article}
            draft={draft}
            categories={categories}
            tagSuggestions={tagSuggestions}
            busy={busy}
            onChange={patch}
          />

          <Button
            className="w-full"
            disabled={busy || !dirty || !valid}
            onClick={() => void save()}
          >
            Save
          </Button>

          {/* Only for someone who may actually publish. The route is behind
              `news.publish`, so showing it to an author who may write but not
              publish would be offering a control that answers 403. */}
          {canPublish && <ScheduleCard articleId={article_id} />}
        </aside>
      </div>
    </PageShell>
  );
}

ArticleEditor.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
