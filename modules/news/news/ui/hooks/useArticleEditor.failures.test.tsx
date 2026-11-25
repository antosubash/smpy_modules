// @vitest-environment happy-dom
import { act } from 'react';
import { expect, it, vi } from 'vitest';
import { updateArticle } from '../utils/api';
import { article, editor, FIRST, json, requests, STALE } from './articleEditor-test-support';

it('saves a corrected slug after a collision without Reload', async () => {
  await act(async () => editor.patch({ slug: 'taken' }));
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: 'Slug already in use' }, 409));
  await act(async () => {
    await editor.save();
  });
  expect(editor.error).toBe('Slug already in use');
  expect(editor.conflict).toBe(false);
  await act(async () => editor.patch({ slug: 'available' }));
  await act(async () => {
    await editor.save();
  });
  expect(requests.find((r) => r.method === 'PUT')?.body).toMatchObject({
    slug: 'available',
    expected_updated_at: FIRST,
  });
  expect(editor.saved).toBe(true);
  expect(editor.error).toBeNull();
});

it.each([409, 422, 404, 500, 'network'] as const)(
  'a %s failure affects only its write, including an already queued successor',
  async (failure) => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.mocked(fetch).mockImplementationOnce(async () => {
      await gate;
      if (failure === 'network') throw new Error('Connection lost');
      return json({ detail: 'This write failed' }, failure);
    });
    let first!: Promise<boolean>;
    let next!: Promise<boolean>;
    await act(async () => {
      first = editor.writeArticle((version) =>
        updateArticle(7, { author: 'First', expected_updated_at: version }),
      );
      next = editor.writeArticle((version) =>
        updateArticle(7, { author: 'Next', expected_updated_at: version }),
      );
    });
    await act(async () => {
      release();
      expect(await first).toBe(false);
      expect(await next).toBe(true);
    });
    expect(requests.filter((r) => r.method === 'PUT')).toHaveLength(1);
    expect(editor.conflict).toBe(false);
  },
);

it('repeats the conflict banner on a local refusal and Reload reopens the queue', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: STALE, code: 'article_conflict' }, 409));
  await act(async () => {
    await editor.save();
  });
  expect(editor.conflict).toBe(true);
  await act(async () => editor.setError(null));
  const before = vi.mocked(fetch).mock.calls.length;
  await act(async () => {
    await editor.save();
  });
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(before);
  expect(editor.error).toBe(STALE);
  expect(editor.conflict).toBe(true);
  await act(async () => {
    await editor.load();
    await editor.save();
  });
  expect(editor.conflict).toBe(false);
  expect(editor.saved).toBe(true);
});

it('shows each ordinary write failure in its own words', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: 'Invalid title' }, 422));
  await act(async () => {
    await editor.save();
  });
  expect(editor.error).toBe('Invalid title');
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: 'Server unavailable' }, 500));
  await act(async () => {
    await editor.save();
  });
  expect(editor.error).toBe('Server unavailable');
  vi.mocked(fetch).mockRejectedValueOnce(new Error('Connection lost'));
  await act(async () => {
    await editor.save();
  });
  expect(editor.error).toBe('Connection lost');
  vi.mocked(fetch).mockResolvedValueOnce(json(article()));
  await act(async () => {
    await editor.save();
  });
  expect(editor.saved).toBe(true);
});
