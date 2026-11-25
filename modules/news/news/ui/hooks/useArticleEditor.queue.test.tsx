// @vitest-environment happy-dom
import { updateI18n } from '@simple-module-py/i18n';
import { act } from 'react';
import { toast } from 'sonner';
import { afterEach, expect, it, vi } from 'vitest';
import de from '../../locales/de.json';
import { article, click, editor, FIRST, json, STALE } from './articleEditor-test-support';

const GERMAN =
  'Dieser Artikel wurde an anderer Stelle geändert. Laden Sie die aktuelle Version neu und nehmen Sie Ihre Änderung dann erneut vor.';

function german() {
  const messages: Record<string, string> = {};
  function flatten(node: Record<string, unknown>, prefix: string) {
    for (const [key, value] of Object.entries(node)) {
      if (typeof value === 'string') messages[`${prefix}.${key}`] = value;
      else flatten(value as Record<string, unknown>, `${prefix}.${key}`);
    }
  }
  flatten(de, 'news');
  updateI18n({ locale: 'de', messages });
}

afterEach(() => {
  act(() => updateI18n({ locale: 'en', messages: {} }));
  vi.restoreAllMocks();
});

function delayedServer(conflict = false) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const original = vi.mocked(fetch).getMockImplementation();
  if (!original) throw new Error('Test fetch handler is missing');
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  let version = FIRST;
  let conflicts = 0;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (!init?.method || init.method === 'GET') return original(input, init);
    const url = String(input);
    const body = JSON.parse(String(init.body));
    writes.push({ url, body });
    if (writes.length === 1) await gate;
    if (conflict || body.expected_updated_at !== version) {
      conflicts++;
      return json({ detail: STALE, code: 'article_conflict' }, 409);
    }
    if (url.endsWith('/tags')) return json([]);
    version = `2026-01-01T00:00:${String(writes.length).padStart(2, '0')}Z`;
    return json({ ...article(), updated_at: version });
  });
  return { release, writes, conflicts: () => conflicts };
}

it.each([
  ['side', 'main'],
  ['main', 'side'],
  ['side', 'main', 'schedule'],
])('serializes rapid writes %j with send-time versions', async (...actions) => {
  const server = delayedServer();
  await act(async () => editor.patch({ title: 'Pending headline' }));
  const pending: Promise<unknown>[] = [];
  try {
    for (const action of actions) {
      if (action === 'main') {
        await act(async () => {
          pending.push(editor.save());
        });
      } else await click(action === 'side' ? 'Save search settings' : 'Save schedule');
    }
    expect(editor.busy).toBe(true);
    expect(server.writes).toHaveLength(1);
  } finally {
    await act(async () => {
      server.release();
      await Promise.all(pending);
    });
  }
  // The main Save includes tags; those share the metadata response's stamp.
  const expected =
    actions[0] === 'main'
      ? [FIRST, '2026-01-01T00:00:01Z', '2026-01-01T00:00:01Z']
      : actions.length === 3
        ? [FIRST, '2026-01-01T00:00:01Z', '2026-01-01T00:00:02Z', '2026-01-01T00:00:02Z']
        : [FIRST, '2026-01-01T00:00:01Z', '2026-01-01T00:00:02Z'];
  expect(server.writes.map((w) => w.body.expected_updated_at)).toEqual(expected);
  expect(server.conflicts()).toBe(0);
  expect(editor.conflict).toBe(false);
  expect(editor.busy).toBe(false);
  expect(document.querySelector<HTMLButtonElement>('button[disabled]')).toBeNull();
});

it('drops queued writes after a predecessor conflicts and clears pending states', async () => {
  const server = delayedServer(true);
  const error = vi.spyOn(toast, 'error');
  let saving!: Promise<unknown>;
  await click('Save search settings');
  await act(async () => {
    saving = editor.save();
  });
  await click('Save schedule');
  await act(async () => {
    server.release();
    await saving;
  });
  expect(server.writes).toHaveLength(1);
  expect(editor.conflict).toBe(true);
  expect(editor.error).toBe(STALE);
  // Both side writes explain their refusal, including the locally blocked one.
  expect(error).toHaveBeenCalledTimes(2);
  expect(editor.busy).toBe(false);
  expect(document.querySelector<HTMLButtonElement>('button[disabled]')).toBeNull();
  await act(async () => {
    await editor.load();
  });
  await click('Save search settings');
  expect(server.writes).toHaveLength(2);
});

it.each(['main', 'side'])('translates a German conflict on %s Save', async (action) => {
  await act(async () => german());
  vi.mocked(fetch).mockResolvedValue(json({ detail: STALE, code: 'article_conflict' }, 409));
  const error = vi.spyOn(toast, 'error');
  if (action === 'main')
    await act(async () => {
      await editor.save();
    });
  else await click(de.seo.save);
  expect(editor.error).toBe(GERMAN);
  if (action === 'side') expect(error).toHaveBeenCalledWith(GERMAN);
});

it('reuses one translated toast for repeated local conflict refusals', async () => {
  await act(async () => german());
  const error = vi.spyOn(toast, 'error');
  vi.mocked(fetch).mockResolvedValueOnce(json({ detail: STALE, code: 'article_conflict' }, 409));
  await click(de.seo.save);
  await click(de.seo.save);
  await click(de.seo.save);
  expect(editor.error).toBe(GERMAN);
  expect(error).toHaveBeenCalledTimes(3);
  const firstId = error.mock.results[0].value;
  expect(firstId).toBeDefined();
  expect(error.mock.calls.slice(1).map((call) => call[1]?.id)).toEqual([firstId, firstId]);
});

it('queues the header Publish behind main Save and before a side write', async () => {
  const server = delayedServer();
  await act(async () => editor.patch({ title: 'Pending headline' }));
  let saving!: Promise<unknown>;
  let publishing!: Promise<unknown>;
  await act(async () => {
    saving = editor.save();
    publishing = editor.publish();
  });
  await click('Save search settings');
  await act(async () => {
    server.release();
    await Promise.all([saving, publishing]);
  });
  expect(server.writes.map((w) => w.url)).toEqual([
    '/api/news/articles/7',
    '/api/news/articles/7/tags',
    '/api/news/articles/7/publish',
    '/api/news/articles/7',
  ]);
  expect(server.writes.map((w) => w.body.expected_updated_at)).toEqual([
    FIRST,
    '2026-01-01T00:00:01Z',
    '2026-01-01T00:00:01Z',
    '2026-01-01T00:00:03Z',
  ]);
  expect(server.conflicts()).toBe(0);
  expect(editor.busy).toBe(false);
});
