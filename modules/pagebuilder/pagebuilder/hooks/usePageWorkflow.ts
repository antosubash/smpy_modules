/** Save, publish, and approval-workflow actions for the page editor. */

import { router } from '@inertiajs/react';
import type { Data } from '@measured/puck';

import {
  approvePage,
  createPage,
  promptAndReject,
  publishPage,
  savePage,
  submitPage,
  unpublishPage,
} from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';
import type { EditorForm } from './useEditorForm';

interface Params {
  form: EditorForm;
  setBusy: (v: boolean) => void;
  setMessage: (v: string | null) => void;
  markSaved: (payload: EditorSnapshot) => void;
}

export interface PageWorkflow {
  handleSave: (newData: Data) => Promise<void>;
  handlePublish: () => Promise<void>;
  handleUnpublish: () => Promise<void>;
  handleSubmitForReview: () => Promise<void>;
  handleApprove: () => Promise<void>;
  handleReject: () => Promise<void>;
}

export function usePageWorkflow({ form, setBusy, setMessage, markSaved }: Params): PageWorkflow {
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
        setMessage('Draft saved.');
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const handlePublish = async () => {
    if (form.pageId === null) {
      await handleSave(form.data);
      return;
    }
    // Prompt returns `null` on Cancel, `''` on bare-press Enter — only
    // ``null`` should abort. An empty string means "publish, no note".
    const noteInput = window.prompt(
      'Optional message describing this publish (leave blank to skip):',
      '',
    );
    if (noteInput === null) return;
    const note = noteInput.trim() || null;
    setBusy(true);
    setMessage(null);
    try {
      await savePage(form.pageId, draftPayload(form.data));
      markSaved(snapshotWith(form.data));
      const result = await publishPage(form.pageId, note);
      form.setStatus(result.status);
      setMessage('Published.');
      router.reload({ only: ['revisions'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Publish failed');
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
      setMessage('Unpublished.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Unpublish failed');
    } finally {
      setBusy(false);
    }
  };

  const handleSubmitForReview = async () => {
    if (form.pageId === null) {
      setMessage('Save a draft first.');
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await savePage(form.pageId, draftPayload(form.data));
      markSaved(snapshotWith(form.data));
      const result = await submitPage(form.pageId);
      form.setStatus(result.status);
      setMessage('Submitted for review.');
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Submit failed');
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
      setMessage('Approved and published.');
      router.reload({ only: ['revisions', 'page'] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Approve failed');
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (form.pageId === null) return;
    setBusy(true);
    setMessage(null);
    const result = await promptAndReject(form.pageId);
    setBusy(false);
    if ('skipped' in result) {
      if (result.skipped !== 'cancelled') setMessage(result.skipped);
      return;
    }
    form.setStatus(result.status);
    setMessage('Sent back to draft.');
    router.reload({ only: ['revisions', 'page'] });
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
