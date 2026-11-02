// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ImportJob } from '../utils/types';
import { flush, job, stubFetch } from './support';
import { act, click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { ImportsTab } = await import('../components/imports/ImportsTab');
const _Collection = (await import('../../pages/Collection')).default;

const LIST = 'GET /api/images/collections/c1/imports';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('Imports jobs panel', () => {
  it('shows progress and counts, and the controls the state allows', async () => {
    stubFetch({
      [LIST]: {
        items: [
          job({ id: 'run', status: 'running', total_count: 10, done_count: 4, failed_count: 1 }),
          job({ id: 'pau', status: 'paused' }),
          job({
            id: 'bad',
            status: 'failed',
            failed_count: 2,
            errors: [{ code: 'too_many_features' }],
          }),
          job({ id: 'ok', status: 'completed' }),
        ],
      },
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    const rows = view.all('[data-testid="images-import-job"]');
    const controls = rows.map((r) =>
      Array.from(r.querySelectorAll('button[data-testid^="images-import-"]'))
        .map((b) => b.getAttribute('data-testid')?.replace('images-import-', ''))
        .filter((n) => n !== 'delete'),
    );
    expect(controls).toEqual([
      ['pause'],
      ['resume', 'restart'],
      ['restart', 'retry-failed'],
      ['restart'],
    ]);
    expect(rows[0].textContent).toContain('5 of 10 processed');
    expect(rows[0].textContent).toContain('4 added, 0 duplicates, 1 failed');
    expect(rows[2].textContent).toContain('more features than one import may hold');
    await view.unmount();
  });

  it('hides every control from someone who cannot edit', async () => {
    stubFetch({ [LIST]: { items: [job({ status: 'failed', failed_count: 1 })] } });
    const view = await mount(<ImportsTab collectionId="c1" canEdit={false} />);
    await flush();
    expect(view.all('[data-testid="images-import-job"] button')).toHaveLength(0);
    expect(view.find('[data-testid="images-import-new"]')).toBeNull();
    await view.unmount();
  });

  it('marks a silent runner stalled and offers resume instead of pause', async () => {
    stubFetch({
      [LIST]: {
        items: [
          job({
            status: 'running',
            heartbeat_at: new Date(Date.now() - 20 * 60_000).toISOString(),
          }),
        ],
      },
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    expect(view.find('[data-testid="images-import-status"]')?.textContent).toBe('Stalled');
    expect(view.find('[data-testid="images-import-resume"]')).not.toBeNull();
    expect(view.find('[data-testid="images-import-pause"]')).toBeNull();
    await view.unmount();
  });

  it('words a recorded failure code, including the stalled one', async () => {
    stubFetch({
      [LIST]: {
        items: [
          job({
            status: 'failed',
            errors: [{ code: 'stalled' }, { code: 'source_http_404' }, { code: 'nested_archive' }],
          }),
        ],
      },
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    const text = view.find('[data-testid="images-import-errors"]')?.textContent ?? '';
    expect(text).toContain('stopped making progress');
    expect(text).toContain('answered with an error (404)');
    expect(text).toContain('another archive');
    await view.unmount();
  });

  it('polls only while a job is active, and runs a control', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let status: ImportJob['status'] = 'running';
    const calls = stubFetch({
      [LIST]: () => ({ items: [job({ status, done_count: 1 })] }),
      'POST /api/images/imports/j1/pause': () => job({ status: 'paused' }),
    });
    const view = await mount(<ImportsTab collectionId="c1" canEdit />);
    await flush();
    const lists = () => calls.filter((c) => c.method === 'GET').length;
    expect(lists()).toBe(1);
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await flush();
    expect(lists()).toBe(2);

    await click(view.find('[data-testid="images-import-pause"]'));
    await flush();
    expect(view.find('[data-testid="images-import-status"]')?.textContent).toBe('Paused');
    const before = lists();
    status = 'paused';
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    await flush();
    expect(lists()).toBe(before);
    await view.unmount();
  });

  it('reloads the gallery when a running import finishes', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let status: ImportJob['status'] = 'running';
    stubFetch({ [LIST]: () => ({ items: [job({ status })] }) });
    const settled = vi.fn();
    const view = await mount(<ImportsTab collectionId="c1" canEdit onSettled={settled} />);
    await flush();
    status = 'completed';
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    await flush();
    expect(settled).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
