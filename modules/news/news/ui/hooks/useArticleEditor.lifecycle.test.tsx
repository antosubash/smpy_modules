// @vitest-environment happy-dom
import { act } from 'react';
import { toast } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { updateArticle } from '../utils/api';
import {
  article,
  click,
  editor,
  FIRST,
  json,
  setStatus,
  unmountEditor,
} from './articleEditor-test-support';

// React 19 silently ignores late setters, so observe the calls themselves.
const lifecycle = vi.hoisted(() => ({ detached: false, lateUpdates: vi.fn() }));
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>();
  return {
    ...react,
    useState: <T,>(initial: T | (() => T)) => {
      const [value, setValue] = react.useState(initial);
      const tracked = react.useCallback(
        (next: React.SetStateAction<T>) => {
          if (lifecycle.detached) lifecycle.lateUpdates();
          setValue(next);
        },
        [setValue],
      );
      return [value, tracked];
    },
  };
});
beforeEach(() => {
  lifecycle.detached = false;
  lifecycle.lateUpdates.mockClear();
});
afterEach(() => {
  lifecycle.detached = false;
  vi.restoreAllMocks();
});

function server(failure?: number | 'network') {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  const original = vi.mocked(fetch).getMockImplementation();
  let version = FIRST;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (!init?.method || init.method === 'GET') return original?.(url, init) as Promise<Response>;
    const body = init.body ? JSON.parse(String(init.body)) : {};
    writes.push({ url: String(url), body });
    if (writes.length === 1) {
      await gate;
      if (failure === 'network') throw new Error('Offline');
      if (failure)
        return json(
          {
            detail: 'Failed after navigation',
            ...(failure === 409 ? { code: 'article_conflict' } : {}),
          },
          failure,
        );
    }
    if (String(url).endsWith('/tags')) return json([]);
    expect(body.expected_updated_at ?? version).toBe(version);
    version = `2026-01-01T00:00:0${writes.length}Z`;
    return json({ ...article(), updated_at: version });
  });
  return { writes, release };
}
async function leave() {
  await unmountEditor();
  lifecycle.detached = true;
}

it('Save then navigate away immediately still sends and completes without late state or toast', async () => {
  const pendingServer = server();
  const success = vi.spyOn(toast, 'success');
  let saving!: Promise<unknown>;
  act(() => {
    saving = editor.save();
  });
  await leave();
  await act(async () => {
    pendingServer.release();
    await saving;
  });
  expect(pendingServer.writes.map((w) => w.url)).toEqual([
    '/api/news/articles/7',
    '/api/news/articles/7/tags',
  ]);
  expect(lifecycle.lateUpdates).not.toHaveBeenCalled();
  expect(success).not.toHaveBeenCalled();
});

it('drains explicitly requested side saves, Save, Publish and Trash after unmount in order', async () => {
  const pendingServer = server();
  const success = vi.spyOn(toast, 'success');
  await click('Save search settings');
  let saving!: Promise<unknown>;
  let publishing!: Promise<unknown>;
  let trashing!: Promise<unknown>;
  act(() => {
    saving = editor.save();
    publishing = editor.publish();
  });
  await click('Save schedule');
  act(() => {
    trashing = editor.trash();
  });
  await leave();
  await act(async () => {
    pendingServer.release();
    // false suppresses caller navigation after a successful detached Trash.
    expect(await trashing).toBe(false);
    await Promise.all([saving, publishing]);
  });
  expect(pendingServer.writes.map((w) => w.url)).toEqual([
    '/api/news/articles/7',
    '/api/news/articles/7',
    '/api/news/articles/7/tags',
    '/api/news/articles/7/publish',
    '/api/news/articles/7/schedule',
    '/api/news/articles/7/trash',
  ]);
  expect(pendingServer.writes.map((w) => w.body.expected_updated_at)).toEqual([
    FIRST,
    '2026-01-01T00:00:01Z',
    '2026-01-01T00:00:02Z',
    '2026-01-01T00:00:02Z',
    '2026-01-01T00:00:04Z',
    undefined,
  ]);
  expect(lifecycle.lateUpdates).not.toHaveBeenCalled();
  expect(success).not.toHaveBeenCalled();
});

it.each([409, 422, 500, 'network'] as const)(
  'logs a detached %s failure and stops successors',
  async (failure) => {
    const pendingServer = server(failure);
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(toast, 'error');
    let first!: Promise<boolean>;
    let next!: Promise<unknown>;
    act(() => {
      first = editor.writeArticle((version) =>
        updateArticle(7, { author: 'Changed', expected_updated_at: version }),
      );
      next = editor.save();
    });
    await leave();
    await act(async () => {
      pendingServer.release();
      expect(await first).toBe(false);
      expect(await next).toBe(false);
    });
    expect(pendingServer.writes).toHaveLength(1);
    expect(warning).toHaveBeenCalledWith(expect.any(String), expect.any(Object));
    expect(error).not.toHaveBeenCalled();
    expect(lifecycle.lateUpdates).not.toHaveBeenCalled();
  },
);

it('logs only safe diagnostic fields from a detached failure', async () => {
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {});
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.mocked(fetch).mockImplementationOnce(async () => {
    await gate;
    return json({ detail: 'Private article text token=secret' }, 500);
  });
  let saving!: Promise<unknown>;
  act(() => {
    saving = editor.save();
  });
  await leave();
  await act(async () => {
    release();
    await saving;
  });
  expect(warning).toHaveBeenCalledWith(expect.any(String), { status: 500 });
});

it.each([false, true])(
  'Trash cancels successors and reports success only while mounted (detached=%s)',
  async (detached) => {
    const pendingServer = server();
    let trashing!: Promise<boolean>;
    let saving!: Promise<unknown>;
    act(() => {
      trashing = editor.trash();
      saving = editor.save();
    });
    if (detached) await leave();
    await act(async () => {
      pendingServer.release();
      expect(await trashing).toBe(!detached);
      expect(await saving).toBe(false);
    });
    expect(pendingServer.writes.map((w) => w.url)).toEqual(['/api/news/articles/7/trash']);
  },
);

it('does not invent writes when an idle editor unmounts', async () => {
  const pendingServer = server();
  await leave();
  expect(pendingServer.writes).toEqual([]);
});

it.each([
  ['Submit for review', 'draft', '/submit'],
  ['Approve', 'submitted_for_review', '/approve'],
  ['Send back', 'submitted_for_review', '/reject'],
  ['Unpublish', 'published', '/unpublish'],
  ['Restore this version', 'draft', '/revisions/1/restore'],
] as const)(
  'finishes a requested %s after navigation without UI effects',
  async (action, status, path) => {
    setStatus(status);
    await act(async () => {
      await editor.load();
    });
    const pendingServer = server();
    const success = vi.spyOn(toast, 'success');
    await click('Save search settings');
    await click(action);
    if (action === 'Send back' || action === 'Unpublish') await click(action);
    if (action === 'Restore this version') await click('Restore');
    let saving!: Promise<unknown>;
    act(() => {
      saving = editor.save();
    });
    await leave();
    await act(async () => {
      pendingServer.release();
      await saving;
    });
    expect(pendingServer.writes.map((w) => w.url)).toEqual([
      '/api/news/articles/7',
      `/api/news/articles/7${path}`,
      '/api/news/articles/7',
      '/api/news/articles/7/tags',
    ]);
    expect(lifecycle.lateUpdates).not.toHaveBeenCalled();
    expect(success).not.toHaveBeenCalled();
  },
);
