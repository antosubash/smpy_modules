// @vitest-environment happy-dom
import { act } from 'react';
import { expect, it, vi } from 'vitest';
import {
  article,
  click,
  editor,
  FIRST,
  json,
  lastSave,
  SECOND,
  STALE,
  save,
  setReject,
  setVersion,
} from './articleEditor-test-support';

it.each(['Save search settings', 'Save schedule'])(
  '%s then main Save sends the returned version and keeps unsaved edits',
  async (button) => {
    await act(async () => editor.patch({ title: 'Unsaved headline' }));
    await click(button);
    expect(editor.draft?.title).toBe('Unsaved headline');
    await act(async () => {
      await editor.save();
    });
    expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
    expect(lastSave()?.body.title).toBe('Unsaved headline');
    expect(editor.conflict).toBe(false);
  },
);

it.each(['metadata', 'tags'])(
  'a rejected %s save then Save uses the last successful version',
  async (failure) => {
    setReject(failure);
    await save();
    expect(editor.error).toContain('Invalid');
    setReject(null);
    await save();
    expect(lastSave()?.body.expected_updated_at).toBe(failure === 'metadata' ? FIRST : SECOND);
    expect(editor.conflict).toBe(false);
    expect(editor.saved).toBe(true);
  },
);

it('publish and unpublish refresh the version without dropping pending inspector edits', async () => {
  await act(async () => editor.patch({ title: 'Pending' }));
  await act(async () => {
    await editor.publish();
  });
  expect(editor.article?.status).toBe('published');
  expect(editor.draft?.title).toBe('Pending');
  expect(editor.dirty).toBe(true);
  await click('Unpublish');
  await click('Unpublish');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
  expect(editor.article?.status).toBe('draft');
});

it('a genuine concurrent edit still shows the 409 message and preserves the draft', async () => {
  setVersion(SECOND);
  await save();
  expect(editor.conflict).toBe(true);
  expect(editor.error).toBe(STALE);
  expect(editor.draft?.title).toBe('Unsaved headline');
});

it('revision restore adopts the restored headline and version while keeping other pending fields', async () => {
  await act(async () => editor.patch({ title: 'Pending headline', author: 'Pending author' }));
  await click('Restore this version');
  await click('Restore');
  expect(editor.draft?.title).toBe('Restored title');
  expect(editor.draft?.author).toBe('Pending author');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
  expect(lastSave()?.body.title).toBe('Restored title');
});

it.each(['Approve', 'Send back'])('review %s refreshes the main form version', async (action) => {
  await act(async () => editor.patch({ title: 'Pending headline' }));
  await click('Submit for review');
  expect(editor.article?.status).toBe('submitted_for_review');
  // The review cooldown prevents double-clicks from triggering a second transition.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 850));
  });
  await click(action);
  if (action === 'Send back') await click(action);
  expect(editor.article?.status).toBe(action === 'Approve' ? 'published' : 'draft');
  expect(editor.draft?.title).toBe('Pending headline');
  await act(async () => {
    await editor.save();
  });
  expect(lastSave()?.body.expected_updated_at).toBe(SECOND);
});

it.each([
  [FIRST, SECOND, 'Newer headline', 'Pending headline'],
  [FIRST, SECOND, 'Original', 'Original'],
  ['2026-01-01T00:00:00.000001Z', '2026-01-01T00:00:00.000002Z', 'Newer', 'Pending headline'],
])(
  'delayed restore %s after %s with headline %s keeps %s',
  async (older, newer, title, expected) => {
    await act(async () => editor.patch({ title: 'Pending headline' }));
    await act(async () => editor.acceptWrite({ ...article(), updated_at: newer, title }));
    await act(async () => editor.acceptWrite({ ...article(), updated_at: older }, true));
    expect(editor.article?.updated_at).toBe(newer);
    expect(editor.draft?.title).toBe(expected);
  },
);

it('tags finishing after a side-card save do not roll the metadata version back', async () => {
  let finishTags!: (response: Response) => void;
  vi.mocked(fetch)
    .mockResolvedValueOnce(json({ ...article(), updated_at: SECOND }))
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finishTags = resolve;
      }),
    );
  await act(async () => editor.patch({ title: 'Pending headline' }));
  let saving!: Promise<unknown>;
  await act(async () => {
    saving = editor.save();
  });
  const third = '2026-01-01T00:00:10Z';
  await act(async () => editor.acceptWrite({ ...article(), updated_at: third }));
  await act(async () => {
    finishTags(json(['Saved tag']));
    await saving;
  });
  expect(editor.article?.updated_at).toBe(third);
  expect(editor.article?.tags).toEqual(['Saved tag']);
});

it('a save answered 404 says the article is gone and stops offering Save', async () => {
  // Someone trashed or purged it while this screen was open.
  setReject('gone');
  await save();
  expect(editor.gone).toBe(true);
  expect(editor.valid).toBe(false);
  expect(editor.error).toBe('This article was moved to the trash or deleted.');
  expect(editor.conflict).toBe(false);
});
