import { Head, router, usePage } from '@inertiajs/react';
import { ConfirmDialog } from '@simple-module-py/pagebuilder/pagebuilder/components/ConfirmDialog';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect } from 'react';

import { ArticleInspector } from '../components/editor/ArticleInspector';
import { ArticleTranslations } from '../components/editor/ArticleTranslations';
import { useArticleEditor } from '../hooks/useArticleEditor';
import { formatArticleDate } from '../utils/api';

/** The article editor — everything about an article except its body.
 *
 * The body is a page-builder document, so it is edited in the page editor and
 * linked to from here rather than re-hosted: an article *is* a page in this
 * codebase, and duplicating that canvas would mean duplicating the block
 * library, the autosave and the revision handling with it. What this screen
 * owns is what a page has no concept of — category, tags, display date, byline,
 * and how the article behaves in feeds.
 */
export default function ArticleEditor() {
  const props = usePage<{
    props: { article_id: number; locales?: string[] };
  }>().props as unknown as { article_id: number; locales?: string[] };
  const { article_id } = props;
  const locales = props.locales ?? [];

  const {
    article,
    draft,
    categories,
    tagSuggestions,
    busy,
    dirty,
    error,
    setError,
    saved,
    load,
    patch,
    save,
    publish,
    detach,
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

  const isDraft = article.page_status === 'draft';
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
            <p className="font-medium">The body lives in the page editor</p>
            <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
              An article is a page here, so its blocks, revisions and autosave are the page editor's
              — the same block library that every other page uses.
            </p>
            <Button className="mt-3" onClick={() => router.visit(article.edit_url)}>
              Edit the body
            </Button>
          </div>

          <ConfirmDialog
            // Low: the page and its body survive; only the news metadata goes.
            level="low"
            title={`Detach “${article.title}”?`}
            description="The page and its body stay. Only the category, tags and date attached to it are removed, and it stops appearing in news feeds."
            confirmLabel="Detach"
            onConfirm={async () => {
              await detach();
              router.visit('/admin/news/');
            }}
            trigger={
              <Button variant="ghost" size="sm" className="text-destructive" disabled={busy}>
                Detach article
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

          <Button className="w-full" disabled={busy || !dirty} onClick={() => void save()}>
            Save
          </Button>

          {/* Only on a multilingual site: a panel listing one language is a
              panel that answers a question nobody asked. */}
          {locales.length > 1 && (
            <ArticleTranslations article={article} locales={locales} onError={setError} />
          )}
        </aside>
      </div>
    </PageShell>
  );
}

ArticleEditor.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
