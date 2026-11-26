// @vitest-environment happy-dom
import { act } from 'react';
import { expect, it, vi } from 'vitest';

import {
  autosave,
  click,
  edit,
  FIRST,
  form,
  pauseNextWrite,
  releaseWrite,
  requests,
  revisions,
  schedule,
  server,
  shown,
  tick,
  unmountEditor,
  workflow,
  writes,
} from './pageEditor-test-support';

it('autosave sends its loaded token and advances it after success', async () => {
  await edit('First edit');
  await tick();
  expect(writes()[0].body.expected_updated_at).toBe(FIRST);
  expect(autosave.isDirty).toBe(false);
  const token = server.updated_at;
  await edit('Second edit');
  await tick();
  expect(writes()[1].body.expected_updated_at).toBe(token);
  expect(server.title).toBe('Second edit');
});

it('shows conflict and stops autosave and queued manual saves until a choice', async () => {
  server.updated_at = '2026-02-01T00:00:00Z';
  server.title = 'Other editor';
  await edit('Local edit');
  await tick();
  expect(shown()).toContain('This page was changed elsewhere');
  expect(autosave.isDirty).toBe(true);
  await edit('Keep typing locally');
  await tick();
  await tick();
  await act(async () => workflow.handleSave(form.data));
  expect(writes()).toHaveLength(1);
  expect(server.title).toBe('Other editor');
});

it('Overwrite bypasses the stale token once then resumes guarded autosave', async () => {
  server.updated_at = '2026-02-01T00:00:00Z';
  await edit('Deliberate overwrite');
  await tick();
  await act(async () => workflow.handleSave(form.data, true));
  expect(writes().at(-1)?.body).not.toHaveProperty('expected_updated_at');
  expect(server.title).toBe('Deliberate overwrite');
  expect(form.writes.conflict).toBe(false);
  const token = server.updated_at;
  await edit('After overwrite');
  await tick();
  expect(writes().at(-1)?.body.expected_updated_at).toBe(token);
  expect(autosave.isDirty).toBe(false);
});

it('serializes manual save behind an in-flight autosave with its returned token', async () => {
  await edit('Autosave');
  pauseNextWrite();
  await tick();
  let manual: Promise<void>;
  await act(async () => {
    manual = workflow.handleSave(form.data);
  });
  expect(writes()).toHaveLength(1);
  await releaseWrite();
  await act(async () => manual);
  expect(writes()).toHaveLength(2);
  expect(writes()[1].body.expected_updated_at).toBe('2026-01-01T00:00:01Z');
  expect(form.writes.conflict).toBe(false);
});

it.each([
  'publish',
  'unpublish',
  'submit',
  'approve',
  'reject',
  'schedule',
  'clear schedule',
  'restore',
])('%s refreshes the next draft save token without losing pending settings', async (action) => {
  await edit('Unsaved title');
  await act(async () => {
    switch (action) {
      case 'publish':
        await workflow.handlePublish(null);
        break;
      case 'unpublish':
        await workflow.handleUnpublish();
        break;
      case 'submit':
        await workflow.handleSubmitForReview();
        break;
      case 'approve':
        await workflow.handleApprove();
        break;
      case 'reject':
        await workflow.handleReject('Revise');
        break;
      case 'schedule':
        await schedule.handleSaveSchedule();
        break;
      case 'clear schedule':
        await schedule.handleClearSchedule();
        break;
      case 'restore':
        await revisions.handleRestore(1);
        break;
    }
  });
  const token = server.updated_at;
  expect(token).not.toBe(FIRST);
  expect(
    requests.filter((r) => r.method !== 'GET').every((r) => 'expected_updated_at' in r.body),
  ).toBe(true);
  expect(form.title).toBe(action === 'restore' ? 'Restored' : 'Unsaved title');
  await act(async () => workflow.handleSave(form.data));
  expect(writes().at(-1)?.body.expected_updated_at).toBe(token);
  expect(form.writes.conflict).toBe(false);
});

it('Save as template advances the version and preserves unsaved title and SEO', async () => {
  await edit('Pending title');
  await act(async () => form.setMetaTitle('Pending SEO'));
  await click('Save as template');
  expect(server.is_template).toBe(true);
  expect(server.title).toBe('Original');
  expect(form.title).toBe('Pending title');
  expect(form.metaTitle).toBe('Pending SEO');
  const token = server.updated_at;
  await tick();
  expect(writes().at(-1)?.body.expected_updated_at).toBe(token);
  expect(server.title).toBe('Pending title');
  expect(server.meta_title).toBe('Pending SEO');
});

it('a failed Overwrite keeps autosave paused', async () => {
  server.updated_at = '2026-02-01T00:00:00Z';
  await edit('Local');
  await tick();
  vi.mocked(fetch).mockImplementationOnce(async () => new Response('', { status: 503 }));
  await act(async () => workflow.handleSave(form.data, true));
  expect(form.writes.conflict).toBe(true);
  const attempts = vi.mocked(fetch).mock.calls.length;
  await edit('Still local');
  await tick();
  expect(vi.mocked(fetch).mock.calls.length).toBe(attempts);
});

it('a successful draft before a refused publish still advances the token', async () => {
  await edit('Saved draft');
  const realFetch = vi.mocked(fetch).getMockImplementation();
  if (!realFetch) throw new Error('Missing fetch fixture');
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/publish')) return new Response('', { status: 403 });
    return realFetch(url, init);
  });
  await act(async () => {
    await expect(workflow.handlePublish(null)).rejects.toThrow();
  });
  const token = server.updated_at;
  await edit('Next draft');
  await act(async () => workflow.handleSave(form.data));
  expect(writes().at(-1)?.body.expected_updated_at).toBe(token);
  expect(server.title).toBe('Next draft');
});

it('an edit while autosave is in flight remains dirty and uses the response token', async () => {
  await edit('In flight');
  pauseNextWrite();
  await tick();
  await edit('Trailing edit');
  await releaseWrite();
  expect(autosave.isDirty).toBe(true);
  await tick();
  expect(writes().at(-1)?.body.expected_updated_at).toBe('2026-01-01T00:00:01Z');
  expect(server.title).toBe('Trailing edit');
  expect(autosave.isDirty).toBe(false);
});

it('drops an already queued save after the editor unmounts', async () => {
  await edit('First');
  pauseNextWrite();
  await tick();
  let queued: Promise<void> | undefined;
  await act(async () => {
    queued = workflow.handleSave(form.data);
  });
  expect(writes()).toHaveLength(1);
  await unmountEditor();
  await releaseWrite();
  await act(async () => queued);
  expect(writes()).toHaveLength(1);
});

it('releases the next queued save after an ordinary failed request', async () => {
  const realFetch = vi.mocked(fetch).getMockImplementation();
  if (!realFetch) throw new Error('Missing fetch fixture');
  let release: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.mocked(fetch).mockImplementationOnce(async () => {
    await pending;
    return new Response('', { status: 503 });
  });
  await edit('First');
  await tick();
  let queued: Promise<void> | undefined;
  await act(async () => {
    queued = workflow.handleSave(form.data);
  });
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  await act(async () => {
    release?.();
  });
  await act(async () => queued);
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  expect(writes().at(-1)?.body.expected_updated_at).toBe(FIRST);
  expect(server.title).toBe('First');
  expect(form.writes.conflict).toBe(false);
});
