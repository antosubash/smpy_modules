/** Top toolbar: title/slug inputs, status badges, and workflow actions. */

import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';

import type { PageDetail } from '../../utils/api';
import { formatSaveLabel, type SaveState } from '../../utils/editorSnapshot';
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
  const saveStateClass =
    saveState === 'error'
      ? 'text-xs text-destructive'
      : isDirty
        ? 'text-xs text-amber-700'
        : 'text-xs text-muted-foreground';

  return (
    <div className="flex flex-wrap items-center gap-3 border-b bg-background px-4 py-2">
      <Button variant="link" size="sm" onClick={() => router.visit('/pagebuilder')}>
        ← All pages
      </Button>
      {/* Explicit widths, not min-w: Input's base class list carries `w-full`,
          which would stretch these across the row and wrap the toolbar onto
          three lines. cn()'s tailwind-merge resolves w-64/w-52 over w-full. */}
      <Input
        type="text"
        value={title}
        onChange={(e) => onTitleChange(e.target.value)}
        placeholder="Page title"
        className="h-8 w-64 shrink-0 text-sm font-medium"
      />
      <Input
        type="text"
        value={effectiveSlug}
        onChange={(e) => onSlugChange(slugify(e.target.value))}
        placeholder="slug"
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
      <div className="ml-auto flex gap-2">
        <Button variant="outline" size="sm" onClick={onToggleSettings}>
          SEO
        </Button>
        <Button variant="outline" size="sm" disabled={pageId === null} onClick={onToggleHistory}>
          History ({revisionCount})
        </Button>
        <Button variant="outline" size="sm" disabled={busy} onClick={onSave}>
          Save draft
        </Button>
        {status === 'published' && (
          <Button variant="outline" size="sm" disabled={busy} onClick={onUnpublish}>
            Unpublish
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
            Submit for review
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
                  Reject
                </Button>
              }
              title="Send this page back to draft?"
              description="The reason reaches the editor in the page header and the revision history, so say what needs to change."
              label="Reason for rejection"
              placeholder="The hero image is still a placeholder."
              submitLabel="Reject"
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
              Approve
            </Button>
          </>
        )}
        {/* An unsaved page has nothing to publish yet — "Publish" saves it and
            navigates into the editor, so asking for a revision note first
            would be asking about a revision that does not exist. */}
        {pageId === null ? (
          <Button size="sm" disabled={busy} onClick={() => void onPublish(null)}>
            Publish
          </Button>
        ) : (
          <NoteDialog
            trigger={
              <Button size="sm" disabled={busy}>
                Publish
              </Button>
            }
            title="Publish this page?"
            description="It goes live immediately. The note is recorded against the revision this publish creates, and is shown in the History panel."
            label="Describe this publish"
            placeholder="Rewrote the intro and swapped the hero image."
            submitLabel="Publish"
            onSubmit={(note) => onPublish(note || null)}
          />
        )}
        {/* Stays an <a>: the e2e selects it with getByRole('link', {name: /^view$/i}). */}
        {status === 'published' && pageId !== null && (
          <a
            href={`/p/${effectiveSlug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-8 items-center rounded-md border px-3 text-sm hover:bg-accent"
          >
            View
          </a>
        )}
      </div>
      {message && <span className="mt-1 w-full text-sm text-muted-foreground">{message}</span>}
    </div>
  );
}
