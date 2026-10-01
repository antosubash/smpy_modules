import { Head, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect } from 'react';
import { editorStatus } from '../components/articleStatus';

import { ArticleDangerZone } from '../components/editor/ArticleDangerZone';
import { ArticleInspector } from '../components/editor/ArticleInspector';
import { ArticleTranslations } from '../components/editor/ArticleTranslations';
import { HistoryCard } from '../components/editor/HistoryCard';
import { ReviewCard } from '../components/editor/ReviewCard';
import { ScheduleCard } from '../components/editor/ScheduleCard';
import { SeoCard } from '../components/editor/SeoCard';
import { useArticleEditor } from '../hooks/useArticleEditor';
import { formatArticleDate } from '../utils/api';
import { keys, useT } from '../utils/i18n';

/** The article editor — everything about an article except its body.
 *
 * The body used to be a page-builder document, so this screen linked out to
 * that module's canvas. News owns the document now and has a canvas of its own
 * next door; the two stay separate because they are edited in genuinely
 * different postures — a form full of short fields that each save
 * independently, and a full-bleed editor.
 */
export default function ArticleEditor() {
  const { t } = useT();
  const copy = keys.news.editor;
  const props = usePage<{
    props: { article_id: number; preview_url: string; locales?: string[] };
  }>().props as unknown as {
    article_id: number;
    /** Where this article renders through the reader's own screen, over the
     *  draft body. Served rather than assembled here, the same way `edit_url`
     *  is on the listing DTO. */
    preview_url: string;
    locales?: string[];
    auth?: { permissions?: string[] };
  };
  const { article_id, preview_url } = props;
  const canPublish = props.auth?.permissions?.includes('news.publish') ?? false;
  const locales = props.locales ?? [];

  const {
    article,
    draft,
    categories,
    tagSuggestions,
    busy,
    dirty,
    valid,
    error,
    conflict,
    gone,
    setError,
    saved,
    load,
    patch,
    save,
    publish,
    remove,
    trash,
  } = useArticleEditor(article_id);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (!article || !draft) {
    return (
      <PageShell title={t(copy.fallback_title)} description={t(copy.loading)}>
        <Head title={t(copy.fallback_title)} />
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <div role="status" aria-label={t(copy.loading_article)} className="space-y-2">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </PageShell>
    );
  }

  const isDraft = article.status === 'draft';
  const isPublished = article.status === 'published';
  const dated = formatArticleDate(article.published_at);
  const status = editorStatus(article.status, dated, t);

  return (
    <PageShell
      title={article.title || t(copy.untitled)}
      description={t(copy.description, { url: article.url, status })}
      actions={
        <>
          <Button variant="outline" onClick={() => router.visit('/admin/news/')}>
            {t(copy.back_to_list)}
          </Button>
          {/* Always available now. This used to be the *only* preview and had
              to hide itself unless `status === 'published'`, because it linked
              at the public URL and that URL 404s anything else — which left
              the reviewer who most wants to check an article with no way to
              look at it. `preview_url` renders the draft through the reader's
              own screen, so it resolves in every state. */}
          <Button variant="outline" asChild>
            <a href={preview_url} target="_blank" rel="noopener noreferrer">
              {t(copy.preview)}
            </a>
          </Button>
          {/* Kept beside it rather than replaced by it: for a published
              article whose author has kept editing, "what am I about to ship"
              and "what do readers have right now" are different questions and
              both get asked. `article` here is the listing DTO (`ArticleRead`),
              whose only signal that the public URL resolves is
              `status === 'published'` — the client-side fetch that fills this
              screen does not carry `has_published`. */}
          {isPublished && (
            <Button variant="outline" asChild>
              <a href={article.url} target="_blank" rel="noopener noreferrer">
                {t(copy.view_live)}
              </a>
            </Button>
          )}
          {isDraft && (
            <Button disabled={busy} onClick={() => void publish()}>
              {t(copy.publish_now)}
            </Button>
          )}
        </>
      }
    >
      <Head title={article.title || t(copy.fallback_title)} />
      {error && (
        <div className="mb-4 flex items-center gap-3 text-sm text-destructive">
          <p className="min-w-0 flex-1">{error}</p>
          {conflict && (
            <Button size="sm" variant="outline" onClick={() => void load()}>
              {t(keys.news.errors.reload)}
            </Button>
          )}
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="space-y-3">
          <div className="rounded-lg border border-dashed p-8 text-center">
            <p className="font-medium">{t(copy.body_card_title)}</p>
            <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
              {t(copy.body_card_description)}
            </p>
            <Button className="mt-3" onClick={() => router.visit(article.edit_url)}>
              {t(copy.edit_body)}
            </Button>
          </div>

          <ArticleDangerZone
            title={article.title}
            isPublished={isPublished}
            busy={busy}
            canPublish={canPublish}
            onDelete={async () => {
              await remove();
              router.visit('/admin/news/');
            }}
            onTrash={async () => {
              await trash();
              router.visit('/admin/news/');
            }}
          />
        </section>

        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide">
              {t(copy.aside_heading)}
            </h2>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {busy ? t(copy.saving) : dirty ? t(copy.unsaved) : saved ? t(copy.saved) : ''}
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

          {!gone && (
            <Button
              className="w-full"
              disabled={busy || !dirty || !valid}
              onClick={() => void save()}
            >
              {t(copy.save)}
            </Button>
          )}

          <ReviewCard article={article} canPublish={canPublish} onChanged={load} />

          {/* Only on a multilingual site: a panel listing one language is a
              panel that answers a question nobody asked. */}
          {locales.length > 1 && (
            <ArticleTranslations article={article} locales={locales} onError={setError} />
          )}

          {/* Only for someone who may actually publish. The route is behind
              `news.publish`, so showing it to an author who may write but not
              publish would be offering a control that answers 403. */}
          {canPublish && <ScheduleCard articleId={article_id} />}

          <SeoCard articleId={article_id} />
          <HistoryCard articleId={article_id} />
        </aside>
      </div>
    </PageShell>
  );
}

ArticleEditor.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
