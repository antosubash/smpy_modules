import { Head, router, usePage } from '@inertiajs/react';
import { Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect } from 'react';

import {
  articlePuckConfig,
  articleViewports,
  emptyArticleData,
} from '../components/body/articlePuckConfig';
import { useArticleBody } from '../hooks/useArticleBody';

/** The canvas an article's body is written in.
 *
 * This screen is the visible half of the split. The body used to be a
 * pagebuilder page, so writing an article meant leaving the news console for
 * that module's editor; news now owns the document and the place it is
 * composed.
 *
 * Its own route rather than a panel on `ArticleEditor`, because the two are
 * edited in different postures: that screen is a column of short fields that
 * each save on their own, and this one wants the whole viewport.
 */
export default function ArticleBody() {
  const { article_id } = usePage<{ props: { article_id: number } }>().props as unknown as {
    article_id: number;
  };

  const { article, data, saveState, error, busy, dirty, load, change, saveNow, publish } =
    useArticleBody(article_id);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // Autosave is debounced, so there is always a window where the newest edit
  // is only in this tab. Without this, closing it inside that window loses the
  // work silently.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const status =
    saveState === 'saving'
      ? 'Saving…'
      : saveState === 'error'
        ? 'Save failed'
        : dirty
          ? 'Unsaved changes'
          : saveState === 'saved'
            ? 'Saved'
            : '';

  return (
    <div className="flex h-screen flex-col">
      {/* This screen renders its own full-height shell instead of
          AuthenticatedLayout, so nothing else mounts BrandingHead for it — and
          the preview would show the framework's default action colour while
          the published article shows the configured one. */}
      <BrandingHead />
      <Head title={article ? `${article.title} — body` : 'Article body'} />

      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.visit(`/admin/news/articles/${article_id}/edit`)}
        >
          ← Article
        </Button>
        <div className="min-w-0 flex-1">
          <p data-testid="article-body-title" className="truncate font-medium">
            {article?.title ?? 'Loading…'}
          </p>
          <p className="truncate text-xs text-muted-foreground">{article?.url}</p>
        </div>
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {status}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !dirty}
          onClick={() => void saveNow()}
        >
          Save draft
        </Button>
        <Button size="sm" disabled={busy} onClick={() => void publish()}>
          {article?.status === 'published' ? 'Update published' : 'Publish'}
        </Button>
      </header>

      {error && (
        <p className="border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">{error}</p>
      )}

      {article?.rejection_note && article.status === 'draft' && (
        <div className="border-b bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>Sent back:</strong> {article.rejection_note}
        </div>
      )}

      {/* Puck scrolls its own panes, so the container only has to stop the
          page from growing past the viewport. */}
      <div className="min-h-0 flex-1">
        {data !== null && (
          <Puck
            config={articlePuckConfig}
            data={data ?? (emptyArticleData as never)}
            viewports={articleViewports}
            iframe={{ enabled: true }}
            // Puck's header renders its own primary "Publish", wired to a
            // plain data change rather than to the workflow. Leaving it would
            // put two differently-behaved Publish buttons on one screen, the
            // louder of which does the quieter thing. The toolbar above is the
            // only publish control; the title, undo/redo and the sidebar
            // toggles stay in Puck's header.
            overrides={{ headerActions: () => <></> }}
            onChange={change}
          />
        )}
      </div>
    </div>
  );
}
