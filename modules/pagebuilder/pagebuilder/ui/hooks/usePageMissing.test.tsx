// @vitest-environment happy-dom
import { act } from 'react';
import { expect, it, vi } from 'vitest';

import { edit, form, revisions, tick, workflow } from './pageEditor-test-support';

it('a missing page cancels queued writes and even explicit overwrites until another id', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        detail: 'Page not found',
        code: 'page_not_found',
      }),
      { status: 404 },
    ),
  );
  await act(async () => {
    await Promise.all([
      workflow.handleSave(form.data, true),
      workflow.handleSave(form.data),
      workflow.handleSave(form.data, true),
    ]);
  });
  expect(form.writes.missing).toBe(true);
  expect(form.writes.conflict).toBe(false);
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  const attempts = vi.mocked(fetch).mock.calls.length;
  await edit('After deletion');
  await tick();
  await tick();
  await act(async () => workflow.handleSave(form.data, true));
  expect(vi.mocked(fetch).mock.calls.length).toBe(attempts);
  await act(async () => form.setPageId(8));
  expect(form.writes.missing).toBe(false);
  await act(async () => workflow.handleSave(form.data));
  expect(vi.mocked(fetch).mock.calls.length).toBe(attempts + 1);
});

it('a missing revision leaves the page writable', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        detail: 'Revision not found',
      }),
      { status: 404 },
    ),
  );
  await act(async () => {
    await expect(revisions.handleRestore(999)).rejects.toThrow('Revision not found');
  });
  expect(form.writes.missing).toBe(false);
  expect(form.writes.conflict).toBe(false);
  await edit('Still exists');
  await tick();
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
});
