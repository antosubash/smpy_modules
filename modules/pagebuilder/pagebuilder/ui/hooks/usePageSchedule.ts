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
  publishAt: string | null;
  setPublishAt: (value: string | null) => void;
  unpublishAt: string | null;
  setUnpublishAt: (value: string | null) => void;
  scheduleError: string | null;
  handleSaveSchedule: () => Promise<void>;
  handleClearSchedule: () => Promise<void>;
}

export function usePageSchedule({ form, setBusy, setMessage }: Params): PageSchedule {
  const { t } = useT();
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  // Inputs are drafts; the form's timestamps describe the accepted schedule.
  const [publishAt, setPublishAt] = useState(form.publishAt);
  const [unpublishAt, setUnpublishAt] = useState(form.unpublishAt);

  const acceptSchedule = (updated: { publish_at: string | null; unpublish_at: string | null }) => {
    form.setPublishAt(updated.publish_at);
    form.setUnpublishAt(updated.unpublish_at);
    setPublishAt(updated.publish_at);
    setUnpublishAt(updated.unpublish_at);
  };

  const handleSaveSchedule = async () => {
    if (form.pageId === null) {
      setScheduleError(t(keys.pagebuilder.workflow.save_first));
      return;
    }
    setScheduleError(null);
    const publish = fromLocalInput(publishAt);
    const unpublish = fromLocalInput(unpublishAt);
    if (publish && unpublish && publish >= unpublish) {
      setScheduleError(t(keys.pagebuilder.schedule.order_error));
      return;
    }
    setBusy(true);
    try {
      const id = form.pageId;
      const updated = await form.writes.run((token) =>
        schedulePage(id, {
          expected_updated_at: token,
          publish_at: publish,
          unpublish_at: unpublish,
        }),
      );
      acceptSchedule(updated);
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
      const id = form.pageId;
      const updated = await form.writes.run((token) =>
        schedulePage(id, {
          expected_updated_at: token,
          publish_at: null,
          unpublish_at: null,
        }),
      );
      acceptSchedule(updated);
      setMessage(t(keys.pagebuilder.schedule.cleared));
    } catch (e) {
      setScheduleError(e instanceof Error ? e.message : t(keys.pagebuilder.schedule.clear_failed));
    } finally {
      setBusy(false);
    }
  };

  return {
    publishAt,
    setPublishAt,
    unpublishAt,
    setUnpublishAt,
    scheduleError,
    handleSaveSchedule,
    handleClearSchedule,
  };
}
