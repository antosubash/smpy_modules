/**
 * The rendered email for the preview pane.
 *
 * An editable draft previews what is on screen (`previewUnsaved`, a POST),
 * debounced so typing is one request; anyone else — a viewer without
 * `can_edit`, or any campaign that has left draft — gets the saved campaign's
 * preview (`api.preview`, a GET), because the POST is for edit holders only
 * (ruling C10). Nothing is requested while the pane is not shown.
 */

import { useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { bodyKey, isComplete } from '../utils/bodyDraft';
import { useT } from '../utils/i18n';
import type { Block, Preview } from '../utils/types';

export const PREVIEW_DELAY_MS = 500;

export interface PreviewInput {
  id: number;
  /** `can_edit` and the campaign is a draft. */
  editable: boolean;
  enabled: boolean;
  subject: string;
  preheader: string;
  body: Block[];
}

export function usePreview(input: PreviewInput) {
  const { t } = useT();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const latest = useRef(input);
  latest.current = input;

  const { id, editable, enabled, subject, preheader } = input;
  const complete = input.body.every(isComplete);
  const key = bodyKey(input.body);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for the body; `latest` holds the current one.
  useEffect(() => {
    // A body with an unfinished block is not sent: the last preview stays.
    if (!enabled || (editable && !complete)) {
      setLoading(false);
      return;
    }
    let current = true;
    const run = async () => {
      setLoading(true);
      try {
        const next = editable
          ? await api.previewUnsaved({ subject, preheader, body: latest.current.body })
          : await api.preview(id);
        if (!current) return;
        setPreview(next);
        setError(null);
      } catch (e) {
        if (current) setError(errorMessage(e, t));
      } finally {
        if (current) setLoading(false);
      }
    };
    // The saved preview does not change as the writer types: no debounce.
    const timer = editable ? setTimeout(() => void run(), PREVIEW_DELAY_MS) : undefined;
    if (!editable) void run();
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [enabled, editable, complete, id, subject, preheader, key, t]);

  return { preview, error, loading };
}
