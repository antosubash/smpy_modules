/** Top toolbar: title/slug inputs, status badges, and workflow actions. */

import { router } from '@inertiajs/react';

import type { PageDetail } from '../../utils/api';
import { formatSaveLabel, type SaveState } from '../../utils/editorSnapshot';
import { slugify } from '../../utils/slugify';
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
  onPublish: () => void;
  onUnpublish: () => void;
  onSubmitForReview: () => void;
  onApprove: () => void;
  onReject: () => void;
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
  return (
    <div className="border-b bg-white px-4 py-2 flex items-center gap-3 flex-wrap">
      <button
        type="button"
        onClick={() => router.visit('/pagebuilder')}
        className="text-gray-600 hover:underline text-sm"
      >
        ← All pages
      </button>
      <input
        type="text"
        value={title}
        onChange={(e) => onTitleChange(e.target.value)}
        placeholder="Page title"
        className="border rounded px-2 py-1 text-sm font-medium min-w-[16rem]"
      />
      <input
        type="text"
        value={effectiveSlug}
        onChange={(e) => onSlugChange(slugify(e.target.value))}
        placeholder="slug"
        className="border rounded px-2 py-1 text-sm font-mono min-w-[12rem]"
      />
      <StatusBadge status={status} />
      <ScheduledBadge status={status} publishAt={publishAt} unpublishAt={unpublishAt} />
      {pageId !== null && (
        <span
          className={
            saveState === 'error'
              ? 'text-xs text-red-600'
              : isDirty
                ? 'text-xs text-amber-700'
                : 'text-xs text-gray-500'
          }
          data-testid="autosave-status"
          title={autosaveError ?? undefined}
        >
          {formatSaveLabel(saveState, isDirty, lastSavedAt, autosaveError)}
        </span>
      )}
      <div className="ml-auto flex gap-2">
        <button
          type="button"
          onClick={onToggleSettings}
          className="px-3 py-1 text-sm rounded border hover:bg-gray-50"
        >
          SEO
        </button>
        <button
          type="button"
          onClick={onToggleHistory}
          disabled={pageId === null}
          className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
        >
          History ({revisionCount})
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onSave}
          className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
        >
          Save draft
        </button>
        {status === 'published' && (
          <button
            type="button"
            disabled={busy}
            onClick={onUnpublish}
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          >
            Unpublish
          </button>
        )}
        {status === 'draft' && (
          <button
            type="button"
            disabled={busy || pageId === null}
            onClick={onSubmitForReview}
            className="px-3 py-1 text-sm rounded border border-amber-500 text-amber-700 hover:bg-amber-50 disabled:opacity-50"
          >
            Submit for review
          </button>
        )}
        {status === 'submitted_for_review' && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={onReject}
              className="px-3 py-1 text-sm rounded border border-red-500 text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              Reject
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onApprove}
              className="px-3 py-1 text-sm rounded bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
            >
              Approve
            </button>
          </>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={onPublish}
          className="px-3 py-1 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
        >
          Publish
        </button>
        {status === 'published' && pageId !== null && (
          <a
            href={`/p/${effectiveSlug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1 text-sm rounded border hover:bg-gray-50"
          >
            View
          </a>
        )}
      </div>
      {message && <span className="w-full text-sm text-gray-600 mt-1">{message}</span>}
    </div>
  );
}
