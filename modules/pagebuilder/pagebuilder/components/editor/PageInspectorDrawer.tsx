import { useEffect, useState } from 'react';

import type { EditorForm } from '../../hooks/useEditorForm';
import type { PageSchedule } from '../../hooks/usePageSchedule';
import type { PageRead, PageTranslationRead } from '../../utils/api';
import { listPages } from '../../utils/pagesApi';
import { PageActions } from './PageActions';
import { PageSettingsPanel } from './PageSettingsPanel';
import { SchedulePanel } from './SchedulePanel';
import { SeoSettingsPanel } from './SeoSettingsPanel';
import { TranslationsPanel } from './TranslationsPanel';

interface Props {
  form: EditorForm;
  schedule: PageSchedule;
  busy: boolean;
  /** Where pages serve publicly, for the slug preview and the delete warning. */
  publicPrefix: string;
  /** Every language the site publishes in, and the one that serves unprefixed. */
  locales: string[];
  defaultLocale: string;
  /** This page's counterparts in other languages, itself included. */
  translations: PageTranslationRead[];
  onMessage: (message: string | null) => void;
}

/**
 * The Page, SEO and Languages tabs of the editor's inspector.
 *
 * "Block" is a tab in the design but not here: it is Puck's own inspector and
 * lives on the canvas, so this drawer carries the ones that describe the page
 * rather than a selection within it.
 *
 * Languages appears only on a multilingual site. A tab that always reads
 * "English, and nothing else" is a tab every author has to learn to ignore.
 */
export function PageInspectorDrawer({
  form,
  schedule,
  busy,
  publicPrefix,
  locales,
  defaultLocale,
  translations,
  onMessage,
}: Props) {
  const multilingual = locales.length > 1;
  const [tab, setTab] = useState<'page' | 'seo' | 'languages'>('page');
  /** Every other page, for the parent select. Loaded when the drawer opens
   *  rather than on mount — most editing sessions never open it. */
  const [otherPages, setOtherPages] = useState<PageRead[]>([]);

  useEffect(() => {
    if (otherPages.length > 0) return;
    // Narrowed to this page's language: breadcrumbs must not cross languages,
    // so offering a German parent for an English page would only let an author
    // build one that the server then resolves away.
    void listPages(undefined, form.locale)
      .then((response) => setOtherPages(response.items.filter((p) => p.id !== form.pageId)))
      // Only the parent select loses its options; the rest of the tab works.
      .catch(() => {});
  }, [otherPages.length, form.pageId, form.locale]);

  return (
    <div className="border-b bg-muted px-4 py-3">
      <div role="tablist" aria-label="Page inspector" className="mb-3 flex gap-1 border-b pb-2">
        {(multilingual ? (['page', 'seo', 'languages'] as const) : (['page', 'seo'] as const)).map(
          (name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              data-testid={`inspector-tab-${name}`}
              onClick={() => setTab(name)}
              className={`rounded-md px-3 py-1 text-sm capitalize transition ${
                tab === name
                  ? 'bg-background font-medium shadow-sm'
                  : 'text-muted-foreground hover:bg-background/60'
              }`}
            >
              {name === 'seo' ? 'SEO' : name}
            </button>
          ),
        )}
      </div>

      {tab === 'languages' ? (
        <TranslationsPanel
          pageId={form.pageId}
          locale={form.locale}
          translations={translations}
          locales={locales}
          defaultLocale={defaultLocale}
          publicPrefix={publicPrefix}
          onError={onMessage}
        />
      ) : tab === 'page' ? (
        <PageSettingsPanel
          title={form.title}
          onTitleChange={form.setTitle}
          slug={form.effectiveSlug}
          onSlugChange={(value) => {
            form.setSlugTouched(true);
            form.setSlug(value);
          }}
          savedSlug={form.savedSlug}
          parentId={form.parentId}
          onParentChange={form.setParentId}
          pages={otherPages}
          showInHeaderNav={form.showInHeaderNav}
          onShowInHeaderNavChange={form.setShowInHeaderNav}
          showInFooter={form.showInFooter}
          onShowInFooterChange={form.setShowInFooter}
          indexInSearch={form.indexInSearch}
          onIndexInSearchChange={form.setIndexInSearch}
          publicPrefix={publicPrefix}
          actions={
            <PageActions
              pageId={form.pageId}
              title={form.title}
              slug={form.effectiveSlug}
              status={form.status}
              publicPrefix={publicPrefix}
              onError={onMessage}
              onNotice={onMessage}
            />
          }
        />
      ) : (
        <SeoSettingsPanel
          metaTitle={form.metaTitle}
          onMetaTitleChange={form.setMetaTitle}
          pageTitle={form.title}
          slug={form.effectiveSlug}
          publicPrefix={publicPrefix}
          host={typeof window === 'undefined' ? 'example.org' : window.location.host}
          metaDescription={form.metaDescription}
          onMetaDescriptionChange={form.setMetaDescription}
          ogImage={form.ogImage}
          onOgImageChange={form.setOgImage}
          canonicalUrl={form.canonicalUrl}
          onCanonicalUrlChange={form.setCanonicalUrl}
          indexInSearch={form.indexInSearch}
          onIndexInSearchChange={form.setIndexInSearch}
          jsonLdText={form.jsonLdText}
          jsonLdError={form.jsonLdError}
          onJsonLdChange={form.handleJsonLdChange}
          schedule={
            <SchedulePanel
              publishAt={form.publishAt}
              unpublishAt={form.unpublishAt}
              onPublishAtChange={form.setPublishAt}
              onUnpublishAtChange={form.setUnpublishAt}
              onSave={schedule.handleSaveSchedule}
              onClear={schedule.handleClearSchedule}
              saveDisabled={busy || form.pageId === null}
              clearDisabled={
                busy ||
                form.pageId === null ||
                (form.publishAt === null && form.unpublishAt === null)
              }
              error={schedule.scheduleError}
            />
          }
        />
      )}
    </div>
  );
}
