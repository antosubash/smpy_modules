/** Scheduled publish / unpublish actions for the page editor. */

import { useState } from 'react';

import { schedulePage } from '../utils/api';
import { fromLocalInput } from '../utils/datetime';
import { keys, useT } from '../utils/i18n';
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
  const { t } = useT();
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  const handleSaveSchedule = async () => {
    if (form.pageId === null) {
      setScheduleError(t(keys.pagebuilder.workflow.save_first));
      return;
    }
    setScheduleError(null);
    const publish = fromLocalInput(form.publishAt);
    const unpublish = fromLocalInput(form.unpublishAt);
    if (publish && unpublish && publish >= unpublish) {
      setScheduleError(t(keys.pagebuilder.schedule.order_error));
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
      setMessage(t(keys.pagebuilder.schedule.saved));
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : t(keys.pagebuilder.schedule.save_failed));
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
      setMessage(t(keys.pagebuilder.schedule.cleared));
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : t(keys.pagebuilder.schedule.clear_failed));
    } finally {
      setBusy(false);
    }
  };

  return { scheduleError, handleSaveSchedule, handleClearSchedule };
}
