import { type Data, Puck } from '@puckeditor/core';
import '@puckeditor/core/puck.css';
import { usePage } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { useMemo, useState } from 'react';

import { NarrowCanvas } from '../components/editor/NarrowCanvas';
import { PageEditorToolbar } from '../components/editor/PageEditorToolbar';
import { PageInspectorDrawer } from '../components/editor/PageInspectorDrawer';
import { RevisionHistoryPanel } from '../components/editor/RevisionHistoryPanel';
import { localizeConfig, localizeViewports } from '../components/localizeConfig';
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
import { keys, useT } from '../utils/i18n';
import { publicPath } from '../utils/locale';
import { slugify } from '../utils/slugify';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`
 *  — the editor only needs it to show the URL, not to build one. */
const PUBLIC_PREFIX = '/p';

interface Props {
  page: PageDetail | null;
  revisions: PageRevisionRead[];
  /** Every language the site publishes in, and the one that serves at the
   *  unprefixed public URL. Server-rendered so the Languages tab paints with
   *  the first response instead of correcting itself a moment later. */
  locales?: string[];
  default_locale?: string;
}

function initialSnapshotFor(page: PageDetail | null): EditorSnapshot {
  const title = page?.title ?? 'Untitled page';
  return {
    // Every default here must match `useEditorForm`'s corresponding useState
    // exactly. A mismatch does not fail loudly — it just makes a freshly
    // opened page report unsaved changes it does not have.
    title,
    // Derived, not `?? ''`: on a new page the form has no saved slug, so
    // `effectiveSlug` is `slugify(title)`. Comparing that against an empty
    // string made every new page dirty from mount, which armed the
    // beforeunload guard on an editor nobody had typed into yet.
    slug: page?.slug ?? slugify(title),
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
  const { t } = useT();
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { page } = props;
  const revisions = props.revisions ?? [];
  const locales = props.locales ?? ['en'];
  const defaultLocale = props.default_locale ?? 'en';
  // ``rejection_note`` lives on the page prop and refreshes after every
  // partial reload — no separate state slot needed.
  const rejectionNote = page?.rejection_note ?? null;

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const form = useEditorForm(page, defaultLocale);
  const isNarrow = useIsNarrow();
  // The palette's labels are written as catalogue keys — see `localizeConfig`
  // for why a module-scope block config cannot resolve them itself.
  const config = useMemo(() => localizeConfig(getPuckConfig(), t), [t]);
  const viewports = useMemo(() => localizeViewports(editorViewports, t), [t]);

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
        viewHref={publicPath(PUBLIC_PREFIX, form.effectiveSlug, form.locale, defaultLocale)}
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
          <strong>{t(keys.pagebuilder.editor.rejected)}</strong> {rejectionNote}
        </div>
      )}

      {showSettings && (
        <PageInspectorDrawer
          form={form}
          schedule={schedule}
          busy={busy}
          publicPrefix={PUBLIC_PREFIX}
          locales={locales}
          defaultLocale={defaultLocale}
          translations={page?.translations ?? []}
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
            config={config}
            data={form.data}
            viewports={viewports}
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
