/** Revision compare and restore actions for the page editor. */

import { useState } from 'react';

import { diffRevisions, type RevisionDiff, restoreRevision } from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';
import type { EditorForm } from './useEditorForm';

interface Params {
  form: EditorForm;
  setBusy: (v: boolean) => void;
  setMessage: (v: string | null) => void;
  markSaved: (payload: EditorSnapshot) => void;
}

export interface PageRevisions {
  activeDiff: RevisionDiff | null;
  diffError: string | null;
  handleCompare: (beforeId: number, afterId: number) => Promise<void>;
  handleRestore: (revisionId: number) => Promise<void>;
}

export function usePageRevisions({ form, setBusy, setMessage, markSaved }: Params): PageRevisions {
  const [activeDiff, setActiveDiff] = useState<RevisionDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  const handleCompare = async (beforeId: number, afterId: number) => {
    if (form.pageId === null) return;
    if (activeDiff?.after_id === afterId && activeDiff?.before_id === beforeId) {
      setActiveDiff(null);
      return;
    }
    setDiffError(null);
    try {
      const diff = await diffRevisions(form.pageId, beforeId, afterId);
      setActiveDiff(diff);
    } catch (e) {
      setDiffError(e instanceof Error ? e.message : 'Could not load diff');
    }
  };

  // Confirmation lives in the panel's dialog, which also shows a failure —
  // closer to the row than the toolbar message this used to write to.
  const handleRestore = async (revisionId: number) => {
    if (form.pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const restored = await restoreRevision(form.pageId, revisionId);
      markSaved(form.applyRestored(restored));
      setMessage('Revision restored to draft.');
    } finally {
      setBusy(false);
    }
  };

  return { activeDiff, diffError, handleCompare, handleRestore };
}
