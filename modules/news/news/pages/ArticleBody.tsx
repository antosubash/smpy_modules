import { Head, router, usePage } from '@inertiajs/react';
import { Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useMemo } from 'react';

import {
  articlePuckConfig,
  articleViewports,
  emptyArticleData,
} from '../components/body/articlePuckConfig';
import { localizeConfig, localizeViewports } from '../components/body/localizeConfig';
import { useArticleBody } from '../hooks/useArticleBody';
import { useArticleOutline } from '../hooks/useArticleOutline';
import { keys, useT } from '../utils/i18n';

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
  const { t } = useT();
  const copy = keys.news.body;
  const { article_id } = usePage<{ props: { article_id: number } }>().props as unknown as {
    article_id: number;
  };

  const { article, data, saveState, error, busy, dirty, load, change, saveNow, publish } =
    useArticleBody(article_id);

  // What the public viewer passes too, so `Contents` lists the same sections
  // here that a reader will get and every anchor resolves on both screens. The
  // hook keeps the identity stable between heading edits — see its docstring
  // for why handing Puck a fresh object per keystroke would be expensive.
  const outline = useArticleOutline(data);
  const metadata = useMemo(() => ({ outline }), [outline]);

  // The block configs hold catalogue keys where their labels go — see
  // `localizeConfig` for why they cannot resolve them where they are written.
  const config = useMemo(() => localizeConfig(articlePuckConfig, t), [t]);
  const viewports = useMemo(() => localizeViewports(articleViewports, t), [t]);

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
      ? t(copy.saving)
      : saveState === 'error'
        ? t(copy.save_failed)
        : dirty
          ? t(copy.unsaved)
          : saveState === 'saved'
            ? t(copy.saved)
            : '';

  return (
    <div className="flex h-screen flex-col">
      {/* This screen renders its own full-height shell instead of
          AuthenticatedLayout, so nothing else mounts BrandingHead for it — and
          the preview would show the framework's default action colour while
          the published article shows the configured one. */}
      <BrandingHead />
      <Head title={article ? t(copy.title, { title: article.title }) : t(copy.fallback_title)} />

      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.visit(`/admin/news/articles/${article_id}/edit`)}
        >
          {t(copy.back)}
        </Button>
        <div className="min-w-0 flex-1">
          <p data-testid="article-body-title" className="truncate font-medium">
            {article?.title ?? t(copy.loading)}
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
          {t(copy.save_draft)}
        </Button>
        <Button size="sm" disabled={busy} onClick={() => void publish()}>
          {article?.status === 'published' ? t(copy.update_published) : t(copy.publish)}
        </Button>
      </header>

      {error && (
        <p className="border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">{error}</p>
      )}

      {article?.rejection_note && article.status === 'draft' && (
        <div className="border-b bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>{t(copy.sent_back)}</strong> {article.rejection_note}
        </div>
      )}

      {/* Puck scrolls its own panes, so the container only has to stop the
          page from growing past the viewport. */}
      <div className="min-h-0 flex-1">
        {data !== null && (
          <Puck
            config={config}
            data={data ?? (emptyArticleData as never)}
            viewports={viewports}
            iframe={{ enabled: true }}
            metadata={metadata}
            overrides={{
              // Puck's header renders its own primary "Publish", wired to a
              // plain data change rather than to the workflow. Leaving it would
              // put two differently-behaved Publish buttons on one screen, the
              // louder of which does the quieter thing. The toolbar above is
              // the only publish control; the title, undo/redo and the sidebar
              // toggles stay in Puck's header.
              headerActions: () => <></>,
              // With nothing selected Puck shows the *root* field set, and this
              // config deliberately has none — an article's headline is a
              // column, edited next door, not a root prop (see
              // `articlePuckConfig`). That would leave an empty panel where a
              // writer looking for the headline would look first, so it says
              // where the headline went instead.
              fields: ({ children, itemSelector }) =>
                itemSelector ? (
                  <>{children}</>
                ) : (
                  <p className="p-4 text-sm text-muted-foreground">{t(copy.select_a_block)}</p>
                ),
            }}
            onChange={change}
          />
        )}
      </div>
    </div>
  );
}
