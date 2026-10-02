/** Save, publish, and approval-workflow actions for the page editor. */

import { router } from '@inertiajs/react';
import type { Data } from '@puckeditor/core';

import {
  approvePage,
  createPage,
  publishPage,
  rejectPage,
  savePage,
  submitPage,
  unpublishPage,
} from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';
import { keys, useT } from '../utils/i18n';
import type { EditorForm } from './useEditorForm';

interface Params {
  form: EditorForm;
  setBusy: (v: boolean) => void;
  setMessage: (v: string | null) => void;
  markSaved: (payload: EditorSnapshot) => void;
}

export interface PageWorkflow {
  handleSave: (newData: Data) => Promise<void>;
  /** *note* is `null` for "publish, no note". Rejects on failure so the
   *  dialog that collected the note can show why. */
  handlePublish: (note: string | null) => Promise<void>;
  handleUnpublish: () => Promise<void>;
  handleSubmitForReview: () => Promise<void>;
  handleApprove: () => Promise<void>;
  /** Rejects on failure, as `handlePublish` does. */
  handleReject: (note: string) => Promise<void>;
}

export function usePageWorkflow({ form, setBusy, setMessage, markSaved }: Params): PageWorkflow {
  const { t } = useT();
  const snapshotWith = (newData: Data): EditorSnapshot => ({
    ...form.snapshotPayload,
    data: newData,
  });

  const draftPayload = (newData: Data) => ({
    ...form.writePayload(),
    draft_data: newData as unknown as Record<string, unknown>,
  });

  const handleSave = async (newData: Data) => {
    setBusy(true);
    setMessage(null);
    try {
      if (form.pageId === null) {
        const created = await createPage(draftPayload(newData) as Parameters<typeof createPage>[0]);
        form.setPageId(created.id);
        form.setSlug(created.slug);
        form.setSlugTouched(true);
        form.setStatus(created.status);
        router.visit(`/pagebuilder/${created.id}/edit`, { preserveState: false });
      } else {
        const updated = await savePage(form.pageId, draftPayload(newData));
        form.setStatus(updated.status);
        markSaved(snapshotWith(newData));
        setMessage(t(keys.pagebuilder.workflow.draft_saved));
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.workflow.save_failed));
    } finally {
      setBusy(false);
    }
  };

  // Aborting is the dialog's job now — it simply never calls this. That also
  // retires the `null` vs `''` distinction the prompt forced on us: cancelling
  // and publishing without a note are different code paths rather than two
  // readings of one return value.
  const handlePublish = async (note: string | null) => {
    if (form.pageId === null) {
      await handleSave(form.data);
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await savePage(form.pageId, draftPayload(form.data));
      markSaved(snapshotWith(form.data));
      const result = await publishPage(form.pageId, note);
      form.setStatus(result.status);
      setMessage(t(keys.pagebuilder.workflow.published));
      router.reload({ only: ['revisions'] });
    } finally {
      setBusy(false);
    }
  };

  const handleUnpublish = async () => {
    if (form.pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await unpublishPage(form.pageId);
      form.setStatus(result.status);
      setMessage(t(keys.pagebuilder.workflow.unpublished));
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.workflow.unpublish_failed));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitForReview = async () => {
    if (form.pageId === null) {
      setMessage(t(keys.pagebuilder.workflow.save_first));
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await savePage(form.pageId, draftPayload(form.data));
      markSaved(snapshotWith(form.data));
      const result = await submitPage(form.pageId);
      form.setStatus(result.status);
      setMessage(t(keys.pagebuilder.workflow.submitted));
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.workflow.submit_failed));
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async () => {
    if (form.pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await approvePage(form.pageId);
      form.setStatus(result.status);
      setMessage(t(keys.pagebuilder.workflow.approved));
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.workflow.approve_failed));
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async (note: string) => {
    if (form.pageId === null) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await rejectPage(form.pageId, note);
      form.setStatus(result.status);
      setMessage(t(keys.pagebuilder.workflow.rejected));
      router.reload({ only: ['revisions', 'page'] });
    } finally {
      setBusy(false);
    }
  };

  return {
    handleSave,
    handlePublish,
    handleUnpublish,
    handleSubmitForReview,
    handleApprove,
    handleReject,
  };
}
