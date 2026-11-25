// @vitest-environment happy-dom
import { act } from 'react';
import { toast } from 'sonner';
import { expect, it, vi } from 'vitest';
import {
  article,
  click,
  editor,
  FIRST,
  json,
  lastSave,
  requests,
  SECOND,
  STALE,
  setStatus,
  setVersion,
} from './articleEditor-test-support';

const actions = [
  'Save search settings',
  'Save schedule',
  'Publish',
  'Unpublish',
  'Submit for review',
  'Approve',
  'Send back',
  'Restore this version',
];

async function prepare(action: string) {
  if (['Approve', 'Send back', 'Unpublish'].includes(action)) {
    setStatus(action === 'Unpublish' ? 'published' : 'submitted_for_review');
    await act(async () => {
      await editor.load();
    });
  }
  await act(async () => editor.patch({ title: 'Pending headline' }));
}

async function perform(action: string) {
  if (action === 'Publish') {
    await act(async () => {
      await editor.publish();
    });
  } else {
    await click(action);
    if (['Unpublish', 'Send back'].includes(action)) await click(action);
    if (action === 'Restore this version') await click('Restore');
  }
}

it.each(actions)('%s refuses a stale base without advancing the form version', async (action) => {
  await prepare(action);
  setVersion(SECOND); // Another editor saved headline B since this form loaded A.
  const error = vi.spyOn(toast, 'error');
  await perform(action);
  const write = requests.filter((r) => r.method !== 'GET').at(-1);
  expect(write?.body.expected_updated_at).toBe(FIRST);
  expect(editor.article?.updated_at).toBe(FIRST);
  expect(editor.draft?.title).toBe('Pending headline');
  if (action === 'Publish') expect(editor.error).toBe(STALE);
  else expect(error).toHaveBeenCalledWith(STALE);
  error.mockRestore();
  const writes = requests.filter((r) => r.method !== 'GET').length;
  await act(async () => {
    await editor.save();
  });
  expect(requests.filter((r) => r.method !== 'GET')).toHaveLength(writes);
  expect(editor.conflict).toBe(true);
  expect(editor.error).toBe(STALE);
});

it.each(actions)('%s success gives the next main Save the returned version', async (action) => {
  await prepare(action);
  await perform(action);
  const write = requests.filter((r) => r.method !== 'GET').at(-1);
  expect(write?.body.expected_updated_at).toBe(FIRST);
  expect(editor.article?.updated_at).toBe(SECOND);
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
  expect(editor.conflict).toBe(false);
});

it('the tags request uses the metadata response version and refuses a newer edit', async () => {
  const third = '2026-01-01T00:00:10Z';
  vi.mocked(fetch).mockImplementationOnce(async () => {
    setVersion(third); // Someone saves between the metadata and tags requests.
    return json({ ...article(), updated_at: SECOND });
  });
  await act(async () => editor.patch({ tags: ['Pending tag'] }));
  await act(async () => {
    await editor.save();
  });
  expect(requests.at(-1)?.body.expected_updated_at).toBe(SECOND);
  expect(editor.article?.updated_at).toBe(SECOND);
  expect(editor.draft?.tags).toEqual(['Pending tag']);
  expect(editor.conflict).toBe(true);
  expect(editor.error).toBe(STALE);
});
