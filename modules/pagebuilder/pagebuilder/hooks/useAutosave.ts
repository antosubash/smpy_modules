/** Dirty tracking, debounced autosave, and the unsaved-changes guard. */

import type { Data } from '@puckeditor/core';
import { useEffect, useMemo, useRef, useState } from 'react';

import { savePage } from '../utils/api';
import {
  AUTOSAVE_DEBOUNCE_MS,
  type EditorSnapshot,
  type SaveState,
  snapshotKey,
} from '../utils/editorSnapshot';

interface Params {
  pageId: number | null;
  busy: boolean;
  data: Data;
  snapshotPayload: EditorSnapshot;
  initialSnapshot: EditorSnapshot;
  writePayload: () => Record<string, unknown>;
}

export interface Autosave {
  isDirty: boolean;
  saveState: SaveState;
  lastSavedAt: Date | null;
  autosaveError: string | null;
  markSaved: (payload: EditorSnapshot) => void;
}

export function useAutosave({
  pageId,
  busy,
  data,
  snapshotPayload,
  initialSnapshot,
  writePayload,
}: Params): Autosave {
  // Memoize the stringify — Puck ``data`` can be hundreds of KB on a
  // populated page, and the component re-renders on every keystroke.
  // Depending on the `snapshotPayload` object itself would defeat the memo —
  // the caller rebuilds it every render. The fields listed are its full contents.
  // biome-ignore lint/correctness/useExhaustiveDependencies: listed fields are the object's full contents
  const currentSnapshot = useMemo(
    () => snapshotKey(snapshotPayload),
    [
      snapshotPayload.title,
      snapshotPayload.slug,
      snapshotPayload.metaDescription,
      snapshotPayload.ogImage,
      snapshotPayload.canonicalUrl,
      snapshotPayload.indexInSearch,
      snapshotPayload.jsonLdText,
      snapshotPayload.data,
    ],
  );

  // Intentionally mount-only. Inertia remounts the editor on a different page
  // id, which is exactly when a fresh baseline is wanted; recomputing on prop
  // identity would reset the dirty state mid-edit.
  // biome-ignore lint/correctness/useExhaustiveDependencies: mount-only baseline is deliberate
  const baseline = useMemo(() => snapshotKey(initialSnapshot), []);

  const [savedSnapshot, setSavedSnapshot] = useState<string>(baseline);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [autosaveError, setAutosaveError] = useState<string | null>(null);

  const isDirty = currentSnapshot !== savedSnapshot;

  const markSaved = (payload: EditorSnapshot) => {
    setSavedSnapshot(snapshotKey(payload));
    setSaveState('idle');
    setLastSavedAt(new Date());
    setAutosaveError(null);
  };

  // Debounced autosave. If the user keeps editing while a save is in
  // flight, ``saveState`` flips back to ``'idle'`` in the finally block,
  // which re-runs this effect; ``isDirty`` is still true relative to the
  // just-stored snapshot, so a fresh debounce window arms automatically
  // — the trailing edit isn't lost.
  //
  // New (unsaved) pages opt out: the first save creates the row and
  // redirects, which can't sensibly happen on a background timer.
  const autosaveInFlight = useRef(false);
  // `data` and `writePayload` are read inside the timeout, not at effect setup.
  // Adding them would re-arm the debounce on every keystroke and the save would
  // never fire; `currentSnapshot` already changes whenever they do.
  // biome-ignore lint/correctness/useExhaustiveDependencies: deps are read in the timeout, not at setup
  useEffect(() => {
    if (pageId === null) return;
    if (!isDirty) return;
    if (busy) return;
    if (autosaveInFlight.current) return;
    const handle = window.setTimeout(async () => {
      autosaveInFlight.current = true;
      const snapshotAtSave = currentSnapshot;
      const payload = {
        ...writePayload(),
        draft_data: data as unknown as Record<string, unknown>,
      };
      setSaveState('saving');
      try {
        await savePage(pageId, payload);
        setSavedSnapshot(snapshotAtSave);
        setLastSavedAt(new Date());
        setAutosaveError(null);
        setSaveState('idle');
      } catch (e) {
        setAutosaveError(e instanceof Error ? e.message : 'Save failed');
        setSaveState('error');
      } finally {
        autosaveInFlight.current = false;
      }
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [pageId, isDirty, busy, currentSnapshot, saveState]);

  // beforeunload: only attached while dirty, so the browser confirm
  // doesn't fire on a clean exit.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Required by the spec; most browsers ignore the actual string.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  return { isDirty, saveState, lastSavedAt, autosaveError, markSaved };
}
