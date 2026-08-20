import { type Data, Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { useState } from 'react';

import { NarrowCanvas } from '../components/editor/NarrowCanvas';
import { PageEditorToolbar } from '../components/editor/PageEditorToolbar';
import { PageInspectorDrawer } from '../components/editor/PageInspectorDrawer';
import { RevisionHistoryPanel } from '../components/editor/RevisionHistoryPanel';
import { migrateContent } from '../components/migrateContent';
import { editorViewports, emptyData, getPuckConfig } from '../components/puckConfig';
import { useAutosave } from '../hooks/useAutosave';
import { useEditorForm } from '../hooks/useEditorForm';
import { useIsNarrow } from '../hooks/useIsNarrow';
import { usePageRevisions } from '../hooks/usePageRevisions';
import { usePageSchedule } from '../hooks/usePageSchedule';
import { usePageWorkflow } from '../hooks/usePageWorkflow';
import type { PageDetail, PageRevisionRead } from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`
 *  — the editor only needs it to show the URL, not to build one. */
const PUBLIC_PREFIX = '/p';

interface Props {
  page: PageDetail | null;
  revisions: PageRevisionRead[];
}

function initialSnapshotFor(page: PageDetail | null): EditorSnapshot {
  return {
    // Every default here must match `useEditorForm`'s corresponding useState
    // exactly. A mismatch does not fail loudly — it just makes a freshly
    // opened page report unsaved changes it does not have.
    title: page?.title ?? 'Untitled page',
    slug: page?.slug ?? '',
    metaTitle: page?.meta_title ?? '',
    metaDescription: page?.meta_description ?? '',
    ogImage: page?.og_image ?? '',
    canonicalUrl: page?.canonical_url ?? '',
    indexInSearch: page?.index_in_search ?? true,
    jsonLdText: page?.json_ld ? JSON.stringify(page.json_ld, null, 2) : '',
    parentId: page?.parent_id ?? null,
    showInHeaderNav: page?.show_in_header_nav ?? false,
    showInFooter: page?.show_in_footer ?? false,
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
  const [showHistory, setShowHistory] = useState(false);

  const form = useEditorForm(page);
  const isNarrow = useIsNarrow();

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
        <PageInspectorDrawer
          form={form}
          schedule={schedule}
          busy={busy}
          publicPrefix={PUBLIC_PREFIX}
          onMessage={setMessage}
        />
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

      {/* Puck scrolls its own panes; only the narrow outline needs the
          scroll container to be here. */}
      <div className={`flex-1 min-h-0 ${isNarrow ? 'overflow-auto' : ''}`}>
        {isNarrow ? (
          <NarrowCanvas
            data={form.data}
            onChange={form.setData}
            busy={busy}
            previewUrl={form.pageId === null ? null : `/pagebuilder/${form.pageId}/preview`}
          />
        ) : (
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
        )}
      </div>
    </div>
  );
}
