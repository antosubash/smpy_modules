/** Dirty-tracking primitives for the page editor's autosave. */

import type { Data } from '@puckeditor/core';

export const AUTOSAVE_DEBOUNCE_MS = 2000;

export type SaveState = 'idle' | 'saving' | 'error';

/**
 * Everything an edit can change, compared as a whole to decide "is this dirty".
 *
 * It has to list every editable field, not most of them. A field that is in
 * `writePayload` but not here is one the autosave never notices: the status
 * line keeps saying "Saved", the unload guard stays disarmed, and the edit is
 * lost on navigate — while a manual Save would have persisted it, which is
 * what makes the omission so easy to miss.
 */
export interface EditorSnapshot {
  title: string;
  slug: string;
  metaTitle: string;
  metaDescription: string;
  ogImage: string;
  canonicalUrl: string;
  indexInSearch: boolean;
  jsonLdText: string;
  parentId: number | null;
  showInHeaderNav: boolean;
  showInFooter: boolean;
  data: Data;
}

export function snapshotKey(payload: EditorSnapshot): string {
  return JSON.stringify(payload);
}

export function formatSaveLabel(
  state: SaveState,
  isDirty: boolean,
  lastSavedAt: Date | null,
  errorMessage: string | null,
): string {
  if (state === 'saving') return 'Saving…';
  if (state === 'error') return errorMessage ? `Save failed: ${errorMessage}` : 'Save failed';
  if (isDirty) return 'Unsaved changes';
  if (lastSavedAt) {
    const hh = String(lastSavedAt.getHours()).padStart(2, '0');
    const mm = String(lastSavedAt.getMinutes()).padStart(2, '0');
    return `Saved at ${hh}:${mm}`;
  }
  return 'Saved';
}
