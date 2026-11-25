// @vitest-environment happy-dom
import { act } from 'react';
import { toast } from 'sonner';
import { afterEach, expect, it, vi } from 'vitest';
import { updateArticle } from '../utils/api';
import { article, editor, FIRST, json, renderEditor, STALE } from './articleEditor-test-support';

afterEach(() => vi.restoreAllMocks());

function navigationServer(conflict = false) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const versions = new Map([
    [7, FIRST],
    [8, '2026-01-01T00:00:10Z'],
  ]);
  const writes: { id: number; path: string; body: Record<string, unknown> }[] = [];
  const original = vi.mocked(fetch).getMockImplementation();
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const path = String(input);
    const id = Number(path.match(/articles\/(\d+)/)?.[1]);
    if (!id || path.endsWith('/revisions')) return original?.(input, init) as Promise<Response>;
    if (!init?.method || init.method === 'GET')
      return json({ ...article(), id, title: `Article ${id}`, updated_at: versions.get(id) });
    const body = init.body ? JSON.parse(String(init.body)) : {};
    writes.push({ id, path, body });
    if (writes.length === 1) {
      await gate;
      if (conflict) return json({ detail: STALE, code: 'article_conflict' }, 409);
    }
    if (path.endsWith('/tags')) return json([]);
    const updated = id === 7 ? '2026-01-01T00:00:01Z' : '2026-01-01T00:00:11Z';
    versions.set(id, updated);
    return json({ ...article(), id, title: `Article ${id}`, updated_at: updated });
  });
  return { release, writes };
}

it('keeps queued writes and versions with their article when the route reuses the editor', async () => {
  const server = navigationServer();
  const success = vi.spyOn(toast, 'success');
  let side!: Promise<boolean>;
  let saveA!: Promise<unknown>;
  act(() => {
    side = editor.writeArticle((version) => updateArticle(7, { expected_updated_at: version }));
    saveA = editor.save();
  });
  await renderEditor(8);
  let saveB!: Promise<unknown>;
  act(() => {
    saveB = editor.save();
  });
  await act(async () => {
    server.release();
    await Promise.all([side, saveA, saveB]);
  });
  expect(server.writes.filter((w) => w.id === 7).map((w) => w.body.expected_updated_at)).toEqual([
    FIRST,
    '2026-01-01T00:00:01Z',
    '2026-01-01T00:00:01Z',
  ]);
  expect(server.writes.filter((w) => w.id === 8).map((w) => w.body.expected_updated_at)).toEqual([
    '2026-01-01T00:00:10Z',
    '2026-01-01T00:00:11Z',
  ]);
  expect(editor.article?.id).toBe(8);
  expect(editor.saved).toBe(true);
  expect(success).toHaveBeenCalledTimes(1);
});

it('an old article conflict cannot block the new article after route reuse', async () => {
  const server = navigationServer(true);
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {});
  let oldWrite!: Promise<boolean>;
  act(() => {
    oldWrite = editor.writeArticle((version) => updateArticle(7, { expected_updated_at: version }));
  });
  await renderEditor(8);
  await act(async () => {
    server.release();
    await oldWrite;
    await editor.save();
  });
  expect(editor.conflict).toBe(false);
  expect(editor.saved).toBe(true);
  expect(server.writes.some((w) => w.id === 8)).toBe(true);
  expect(warning).toHaveBeenCalledTimes(1);
});

it('resets loaded state and the conflict latch before a different article loads', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: STALE, code: 'article_conflict' }, 409));
  await act(async () => {
    await editor.save();
  });
  expect(editor.conflict).toBe(true);
  vi.mocked(fetch).mockResolvedValue(json({ detail: 'Missing' }, 404));
  await renderEditor(8);
  expect(editor.article).toBeNull();
  expect(editor.draft).toBeNull();
  expect(editor.conflict).toBe(false);
  expect(editor.gone).toBe(true);
});

it('allows loading and saving after the StrictMode effect cleanup and remount', async () => {
  await renderEditor(7, true);
  await act(async () => {
    await editor.save();
  });
  expect(editor.article?.id).toBe(7);
  expect(editor.saved).toBe(true);
  expect(editor.busy).toBe(false);
});
