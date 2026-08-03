/** Scheduled publish / unpublish actions for the page editor. */

import { useState } from 'react';

import { schedulePage } from '../utils/api';
import { fromLocalInput } from '../utils/datetime';
import type { EditorForm } from './useEditorForm';

interface Params {
  form: EditorForm;
  setBusy: (v: boolean) => void;
  setMessage: (v: string | null) => void;
}

export interface PageSchedule {
  scheduleError: string | null;
  handleSaveSchedule: () => Promise<void>;
  handleClearSchedule: () => Promise<void>;
}

export function usePageSchedule({ form, setBusy, setMessage }: Params): PageSchedule {
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  const handleSaveSchedule = async () => {
    if (form.pageId === null) {
      setScheduleError('Save a draft first.');
      return;
    }
    setScheduleError(null);
    const publish = fromLocalInput(form.publishAt);
    const unpublish = fromLocalInput(form.unpublishAt);
    if (publish && unpublish && publish >= unpublish) {
      setScheduleError('Unpublish time must be after publish time.');
      return;
    }
    setBusy(true);
    try {
      const updated = await schedulePage(form.pageId, {
        publish_at: publish,
        unpublish_at: unpublish,
      });
      form.setPublishAt(updated.publish_at);
      form.setUnpublishAt(updated.unpublish_at);
      setMessage('Schedule saved.');
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : 'Could not save schedule');
    } finally {
      setBusy(false);
    }
  };

  const handleClearSchedule = async () => {
    if (form.pageId === null) return;
    setBusy(true);
    setScheduleError(null);
    try {
      const updated = await schedulePage(form.pageId, {
        publish_at: null,
        unpublish_at: null,
      });
      form.setPublishAt(updated.publish_at);
      form.setUnpublishAt(updated.unpublish_at);
      setMessage('Schedule cleared.');
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : 'Could not clear schedule');
    } finally {
      setBusy(false);
    }
  };

  return { scheduleError, handleSaveSchedule, handleClearSchedule };
}
