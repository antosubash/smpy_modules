import { type Data, Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { router, usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useState } from 'react';

import { PageActions } from '../components/editor/PageActions';
import { PageEditorToolbar } from '../components/editor/PageEditorToolbar';
import { PageSettingsPanel } from '../components/editor/PageSettingsPanel';
import { RevisionHistoryPanel } from '../components/editor/RevisionHistoryPanel';
import { SchedulePanel } from '../components/editor/SchedulePanel';
import { SeoSettingsPanel } from '../components/editor/SeoSettingsPanel';
import { migrateContent } from '../components/migrateContent';
import { editorViewports, emptyData, getPuckConfig } from '../components/puckConfig';
import { useAutosave } from '../hooks/useAutosave';
import { useEditorForm } from '../hooks/useEditorForm';
import { usePageRevisions } from '../hooks/usePageRevisions';
import { usePageSchedule } from '../hooks/usePageSchedule';
import { usePageWorkflow } from '../hooks/usePageWorkflow';
import type { PageDetail, PageRead, PageRevisionRead } from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';
import { listPages } from '../utils/pagesApi';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`
 *  — the editor only needs it to show the URL, not to build one. */
const PUBLIC_PREFIX = '/p';

interface Props {
  page: PageDetail | null;
  revisions: PageRevisionRead[];
}

function initialSnapshotFor(page: PageDetail | null): EditorSnapshot {
  return {
    title: page?.title ?? 'Untitled page',
    slug: page?.slug ?? '',
    metaDescription: page?.meta_description ?? '',
    ogImage: page?.og_image ?? '',
    canonicalUrl: page?.canonical_url ?? '',
    indexInSearch: page?.index_in_search ?? true,
    jsonLdText: page?.json_ld ? JSON.stringify(page.json_ld, null, 2) : '',
    // Migrated on the way in rather than on save: a draft the author never
    // touches is never rewritten, so the stored payload only changes shape
    // once they actually edit it.
    data: migrateContent(
      (page?.draft_data as unknown as Data) || (emptyData as unknown as Data),
      getPuckConfig(),
    ),
  };
}

export default function PageEditor() {
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { page } = props;
  const revisions = props.revisions ?? [];
  // ``rejection_note`` lives on the page prop and refreshes after every
  // partial reload — no separate state slot needed.
  const rejectionNote = page?.rejection_note ?? null;

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  /** Which inspector tab the settings drawer is showing. "Block" is Puck's own
   *  inspector and lives on the canvas, so the drawer carries the other two. */
  const [settingsTab, setSettingsTab] = useState<'page' | 'seo'>('page');
  /** Every other page, for the parent select. Loaded when the drawer opens
   *  rather than on mount — most editing sessions never open it. */
  const [otherPages, setOtherPages] = useState<PageRead[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  const form = useEditorForm(page);

  useEffect(() => {
    if (!showSettings || otherPages.length > 0) return;
    void listPages()
      .then((response) => setOtherPages(response.items.filter((p) => p.id !== form.pageId)))
      // Only the parent select loses its options; the rest of the tab works.
      .catch(() => {});
  }, [showSettings, otherPages.length, form.pageId]);

  const { isDirty, saveState, lastSavedAt, autosaveError, markSaved } = useAutosave({
    pageId: form.pageId,
    busy,
    data: form.data,
    snapshotPayload: form.snapshotPayload,
    initialSnapshot: initialSnapshotFor(page),
    writePayload: form.writePayload,
  });

  const workflow = usePageWorkflow({ form, setBusy, setMessage, markSaved });
  const schedule = usePageSchedule({ form, setBusy, setMessage });
  const revisionActions = usePageRevisions({ form, setBusy, setMessage, markSaved });

  return (
    <div className="h-screen flex flex-col">
      {/* These editors render their own full-screen shell instead of
          AuthenticatedLayout, so nothing else mounts BrandingHead for them —
          and the preview would show the framework's default action colour
          while the published page shows the configured one. */}
      <BrandingHead />
      <PageEditorToolbar
        pageId={form.pageId}
        title={form.title}
        onTitleChange={form.setTitle}
        effectiveSlug={form.effectiveSlug}
        onSlugChange={(value) => {
          form.setSlug(value);
          form.setSlugTouched(true);
        }}
        status={form.status}
        publishAt={form.publishAt}
        unpublishAt={form.unpublishAt}
        saveState={saveState}
        isDirty={isDirty}
        lastSavedAt={lastSavedAt}
        autosaveError={autosaveError}
        revisionCount={revisions.length}
        busy={busy}
        message={message}
        onToggleSettings={() => setShowSettings((v) => !v)}
        onToggleHistory={() => setShowHistory((v) => !v)}
        onSave={() => workflow.handleSave(form.data)}
        onPublish={workflow.handlePublish}
        onUnpublish={workflow.handleUnpublish}
        onSubmitForReview={workflow.handleSubmitForReview}
        onApprove={workflow.handleApprove}
        onReject={workflow.handleReject}
      />

      {rejectionNote && form.status === 'draft' && (
        <div className="border-b bg-red-50 px-4 py-3 text-sm text-red-800">
          <strong>Rejected:</strong> {rejectionNote}
        </div>
      )}

      {showSettings && (
        <div className="border-b bg-muted px-4 py-3">
          <div role="tablist" aria-label="Page inspector" className="mb-3 flex gap-1 border-b pb-2">
            {(['page', 'seo'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={settingsTab === tab}
                data-testid={`inspector-tab-${tab}`}
                onClick={() => setSettingsTab(tab)}
                className={`rounded-md px-3 py-1 text-sm capitalize transition ${
                  settingsTab === tab
                    ? 'bg-background font-medium shadow-sm'
                    : 'text-muted-foreground hover:bg-background/60'
                }`}
              >
                {tab === 'seo' ? 'SEO' : 'Page'}
              </button>
            ))}
          </div>

          {settingsTab === 'page' ? (
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
              publicPrefix={PUBLIC_PREFIX}
              actions={
                <PageActions
                  pageId={form.pageId}
                  title={form.title}
                  slug={form.effectiveSlug}
                  status={form.status}
                  publicPrefix={PUBLIC_PREFIX}
                  onError={setMessage}
                  onNotice={setMessage}
                />
              }
            />
          ) : (
            <SeoSettingsPanel
              metaTitle={form.metaTitle}
              onMetaTitleChange={form.setMetaTitle}
              pageTitle={form.title}
              slug={form.effectiveSlug}
              publicPrefix={PUBLIC_PREFIX}
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
      )}

      {showHistory && (
        <RevisionHistoryPanel
          revisions={revisions}
          activeDiff={revisionActions.activeDiff}
          diffError={revisionActions.diffError}
          busy={busy}
          onCompare={revisionActions.handleCompare}
          onRestore={revisionActions.handleRestore}
        />
      )}

      <div className="flex-1 min-h-0">
        <Puck
          config={getPuckConfig()}
          data={form.data}
          viewports={editorViewports}
          iframe={{ enabled: true }}
          // Puck's header renders its own primary "Publish" alongside a copy of
          // the page title. Its Publish was wired to a draft save, so the app
          // showed two identical blue Publish buttons where the louder one did
          // the quieter thing. Dropping headerActions leaves the toolbar above
          // as the only publish control; the title, undo/redo and the sidebar
          // toggles stay in Puck's header.
          //
          // Note for anyone auditing selectors: Puck renders that button as a
          // <span>, not a <button>, so it never appeared in the accessibility
          // tree and the e2e suite could not have caught this.
          overrides={{ headerActions: () => <></> }}
          onChange={form.setData}
        />
      </div>
    </div>
  );
}
