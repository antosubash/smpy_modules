/** Top toolbar: title/slug inputs, status badges, and workflow actions. */

import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';

import type { PageDetail } from '../../utils/api';
import { formatSaveLabel, type SaveState } from '../../utils/editorSnapshot';
import { keys, useT } from '../../utils/i18n';
import { slugify } from '../../utils/slugify';
import { NoteDialog } from '../NoteDialog';
import { ScheduledBadge } from '../ScheduledBadge';
import { StatusBadge } from '../StatusBadge';

interface Props {
  pageId: number | null;
  title: string;
  onTitleChange: (value: string) => void;
  effectiveSlug: string;
  onSlugChange: (value: string) => void;
  /** Where the published page actually answers — locale-prefixed for every
   *  language but the site's default. Passed in rather than built from the
   *  slug here: a translation usually reuses its source's slug, so `/p/{slug}`
   *  would open the *other* language's page. */
  viewHref: string;
  status: PageDetail['status'];
  publishAt: string | null;
  unpublishAt: string | null;
  saveState: SaveState;
  isDirty: boolean;
  lastSavedAt: Date | null;
  autosaveError: string | null;
  revisionCount: number;
  busy: boolean;
  message: string | null;
  onToggleSettings: () => void;
  onToggleHistory: () => void;
  onSave: () => void;
  /** `null` means "publish, no note". Rejects surface in the note dialog. */
  onPublish: (note: string | null) => Promise<void>;
  onUnpublish: () => void;
  onSubmitForReview: () => void;
  onApprove: () => void;
  onReject: (note: string) => Promise<void>;
}

export function PageEditorToolbar({
  pageId,
  title,
  onTitleChange,
  effectiveSlug,
  onSlugChange,
  viewHref,
  status,
  publishAt,
  unpublishAt,
  saveState,
  isDirty,
  lastSavedAt,
  autosaveError,
  revisionCount,
  busy,
  message,
  onToggleSettings,
  onToggleHistory,
  onSave,
  onPublish,
  onUnpublish,
  onSubmitForReview,
  onApprove,
  onReject,
}: Props) {
  const { t } = useT();
  const saveStateClass =
    saveState === 'error'
      ? 'text-xs text-destructive'
      : isDirty
        ? 'text-xs text-amber-700'
        : 'text-xs text-muted-foreground';

  return (
    <div className="flex flex-wrap items-center gap-3 border-b bg-background px-4 py-2">
      <Button variant="link" size="sm" onClick={() => router.visit('/pagebuilder')}>
        {t(keys.pagebuilder.toolbar.back)}
      </Button>
      {/* Explicit widths, not min-w: Input's base class list carries `w-full`,
          which would stretch these across the row and wrap the toolbar onto
          three lines. cn()'s tailwind-merge resolves w-64/w-52 over w-full. */}
      <Input
        type="text"
        value={title}
        onChange={(e) => onTitleChange(e.target.value)}
        placeholder={t(keys.pagebuilder.toolbar.title_placeholder)}
        className="h-8 w-64 shrink-0 text-sm font-medium"
      />
      <Input
        type="text"
        value={effectiveSlug}
        onChange={(e) => onSlugChange(slugify(e.target.value))}
        placeholder={t(keys.pagebuilder.toolbar.slug_placeholder)}
        className="h-8 w-52 shrink-0 font-mono text-sm"
      />
      <StatusBadge status={status} />
      <ScheduledBadge status={status} publishAt={publishAt} unpublishAt={unpublishAt} />
      {pageId !== null && (
        <span
          className={saveStateClass}
          data-testid="autosave-status"
          title={autosaveError ?? undefined}
        >
          {formatSaveLabel(saveState, isDirty, lastSavedAt, autosaveError)}
        </span>
      )}
      {/* Wraps too. The outer toolbar wrapping is not enough — this cluster is
          its own flex line, so without it the six workflow buttons hold a
          minimum width and push the whole admin sideways on a phone. */}
      <div className="ml-auto flex flex-wrap gap-2">
        {/* "Settings" rather than "SEO": the drawer carries the Page tab as
            well now, and opening something labelled SEO onto page settings is
            its own small lie. */}
        <Button variant="outline" size="sm" onClick={onToggleSettings}>
          {t(keys.pagebuilder.toolbar.settings)}
        </Button>
        <Button variant="outline" size="sm" disabled={pageId === null} onClick={onToggleHistory}>
          {t(keys.pagebuilder.toolbar.history, { count: revisionCount })}
        </Button>
        <Button variant="outline" size="sm" disabled={busy} onClick={onSave}>
          {t(keys.pagebuilder.toolbar.save_draft)}
        </Button>
        {status === 'published' && (
          <Button variant="outline" size="sm" disabled={busy} onClick={onUnpublish}>
            {t(keys.pagebuilder.toolbar.unpublish)}
          </Button>
        )}
        {status === 'draft' && (
          <Button
            variant="outline"
            size="sm"
            className="border-amber-500 text-amber-700 hover:bg-amber-50"
            disabled={busy || pageId === null}
            onClick={onSubmitForReview}
          >
            {t(keys.pagebuilder.toolbar.submit)}
          </Button>
        )}
        {status === 'submitted_for_review' && (
          <>
            <NoteDialog
              trigger={
                <Button
                  variant="outline"
                  size="sm"
                  className="border-destructive text-destructive hover:bg-destructive/10"
                  disabled={busy}
                >
                  {t(keys.pagebuilder.toolbar.reject)}
                </Button>
              }
              title={t(keys.pagebuilder.toolbar.reject_title)}
              description={t(keys.pagebuilder.toolbar.reject_description)}
              label={t(keys.pagebuilder.toolbar.reject_label)}
              placeholder={t(keys.pagebuilder.toolbar.reject_placeholder)}
              submitLabel={t(keys.pagebuilder.toolbar.reject)}
              required
              destructive
              onSubmit={onReject}
            />
            <Button
              size="sm"
              className="bg-green-600 text-white hover:bg-green-700"
              disabled={busy}
              onClick={onApprove}
            >
              {t(keys.pagebuilder.toolbar.approve)}
            </Button>
          </>
        )}
        {/* An unsaved page has nothing to publish yet — "Publish" saves it and
            navigates into the editor, so asking for a revision note first
            would be asking about a revision that does not exist. */}
        {pageId === null ? (
          <Button size="sm" disabled={busy} onClick={() => void onPublish(null)}>
            {t(keys.pagebuilder.toolbar.publish)}
          </Button>
        ) : (
          <NoteDialog
            trigger={
              <Button size="sm" disabled={busy}>
                {t(keys.pagebuilder.toolbar.publish)}
              </Button>
            }
            title={t(keys.pagebuilder.toolbar.publish_title)}
            description={t(keys.pagebuilder.toolbar.publish_description)}
            label={t(keys.pagebuilder.toolbar.publish_label)}
            placeholder={t(keys.pagebuilder.toolbar.publish_placeholder)}
            submitLabel={t(keys.pagebuilder.toolbar.publish)}
            onSubmit={(note) => onPublish(note || null)}
          />
        )}
        {/* Stays an <a>: the e2e selects it with getByRole('link', {name: /^view$/i}). */}
        {status === 'published' && pageId !== null && (
          <a
            href={viewHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-8 items-center rounded-md border px-3 text-sm hover:bg-accent"
          >
            {t(keys.pagebuilder.toolbar.view)}
          </a>
        )}
      </div>
      {message && <span className="mt-1 w-full text-sm text-muted-foreground">{message}</span>}
    </div>
  );
}
