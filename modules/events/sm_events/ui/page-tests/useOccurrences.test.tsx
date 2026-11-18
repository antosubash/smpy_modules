// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import { paddedRange } from '../calendar/time/range';
import type { FilterQuery, OccurrenceFetcher, OccurrencePage } from '../calendar/types';
import type { Occurrence } from '../utils/types-events';
import { flush } from './support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { useOccurrences } = await import('../calendar/data/useOccurrences');

const r = (start: string, end: string) => ({ start, end });
const first = r('2026-03-01T00:00:00Z', '2026-04-12T00:00:00Z');
const insideFirst = r('2026-03-08T00:00:00Z', '2026-04-19T00:00:00Z');
const far = r('2026-08-01T00:00:00Z', '2026-09-12T00:00:00Z');
const filters: FilterQuery = { calendars: [], categories: [], types: [], locale: 'en' };

const item = (key: string) => ({ key, title: key }) as Occurrence;
const pageOf = (...keys: string[]): OccurrencePage => ({ items: keys.map(item), truncated: false });

type Pending = {
  signal: AbortSignal;
  resolve: (p: OccurrencePage) => void;
  reject: (e: unknown) => void;
};
function controllable() {
  const pending: Pending[] = [];
  const fetcher = vi.fn<OccurrenceFetcher>(
    (_q, signal) =>
      new Promise<OccurrencePage>((resolve, reject) => {
        pending.push({ signal, resolve, reject });
      }),
  );
  return { fetcher, pending };
}

type Props = {
  fetcher: OccurrenceFetcher;
  visible: { start: string; end: string } | null;
  refreshToken?: number;
  onApi?: (api: ReturnType<typeof useOccurrences>) => void;
};
function Probe({ fetcher, visible, refreshToken = 0, onApi }: Props) {
  const state = useOccurrences({ fetcher, visible, filters, refreshToken });
  onApi?.(state);
  return (
    <div>
      <span data-testid="keys">{state.items.map((i) => i.key).join(',')}</span>
      <span data-testid="loading">{String(state.loading)}</span>
      <span data-testid="truncated">{String(state.truncated)}</span>
      <span data-testid="error">{state.error ? 'error' : ''}</span>
    </div>
  );
}
const text = (view: { host: HTMLElement }, id: string) =>
  view.host.querySelector(`[data-testid=${id}]`)?.textContent;

afterEach(() => {
  document.body.innerHTML = '';
});

it('fetches the padded range once for navigations inside it', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} />);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0]?.[0]).toMatchObject(paddedRange(first));
  pending[0]?.resolve(pageOf('a'));
  await flush();
  await view.render(<Probe fetcher={fetcher} visible={insideFirst} />);
  await flush();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(text(view, 'keys')).toBe('a');
  await view.unmount();
});

it('aborts the previous request when the range moves outside', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} />);
  await view.render(<Probe fetcher={fetcher} visible={far} />);
  expect(pending[0]?.signal.aborted).toBe(true);
  expect(pending[1]?.signal.aborted).toBe(false);
  await view.unmount();
  expect(pending[1]?.signal.aborted).toBe(true);
});

it('drops a late answer for an older range', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} />);
  await view.render(<Probe fetcher={fetcher} visible={far} />);
  pending[1]?.resolve(pageOf('new'));
  await flush();
  pending[0]?.resolve(pageOf('old'));
  await flush();
  expect(text(view, 'keys')).toBe('new');
  expect(text(view, 'loading')).toBe('false');
  await view.unmount();
});

it('ignores an aborted request instead of showing an error', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} />);
  await view.render(<Probe fetcher={fetcher} visible={far} />);
  pending[0]?.reject(new DOMException('aborted', 'AbortError'));
  await flush();
  expect(text(view, 'error')).toBe('');
  await view.unmount();
});

it('passes truncated through', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} />);
  pending[0]?.resolve({ items: [], truncated: true });
  await flush();
  expect(text(view, 'truncated')).toBe('true');
  await view.unmount();
});

it('shows an error, and retry refetches and clears it', async () => {
  const { fetcher, pending } = controllable();
  let api: ReturnType<typeof useOccurrences> | undefined;
  const view = await mount(
    <Probe
      fetcher={fetcher}
      visible={first}
      onApi={(a) => {
        api = a;
      }}
    />,
  );
  pending[0]?.reject(new Error('boom'));
  await flush();
  expect(text(view, 'error')).toBe('error');
  const { act } = await import('./test-dom');
  await act(async () => api?.retry());
  expect(fetcher).toHaveBeenCalledTimes(2);
  pending[1]?.resolve(pageOf('ok'));
  await flush();
  expect(text(view, 'error')).toBe('');
  expect(text(view, 'keys')).toBe('ok');
  await view.unmount();
});

it('a refreshToken bump clears the cache and refetches the same range', async () => {
  const { fetcher, pending } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={first} refreshToken={0} />);
  pending[0]?.resolve(pageOf('a'));
  await flush();
  await view.render(<Probe fetcher={fetcher} visible={first} refreshToken={1} />);
  expect(fetcher).toHaveBeenCalledTimes(2);
  await view.unmount();
});

it('invalidate refetches even when cached', async () => {
  const { fetcher, pending } = controllable();
  let api: ReturnType<typeof useOccurrences> | undefined;
  const view = await mount(
    <Probe
      fetcher={fetcher}
      visible={first}
      onApi={(a) => {
        api = a;
      }}
    />,
  );
  pending[0]?.resolve(pageOf('a'));
  await flush();
  const { act } = await import('./test-dom');
  await act(async () => api?.invalidate());
  expect(fetcher).toHaveBeenCalledTimes(2);
  await view.unmount();
});

it('does not fetch while visible is null', async () => {
  const { fetcher } = controllable();
  const view = await mount(<Probe fetcher={fetcher} visible={null} />);
  await flush();
  expect(fetcher).not.toHaveBeenCalled();
  await view.unmount();
});
