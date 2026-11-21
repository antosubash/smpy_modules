// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import type { Call } from './support';
import { calendar, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { useCalendars } = await import('../hooks/useCalendars');
const API = '/api/events/calendars';
function Probe() {
  const list = useCalendars();
  return (
    <div>
      {list.items.map((item) => (
        <span key={item.id}>{item.name}</span>
      ))}
      <button type="button" onClick={() => list.setTrashed(true)}>
        Trash
      </button>
      <button type="button" onClick={list.reload}>
        Reload
      </button>
      {list.error}
    </div>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});
it('ignores late Active data after switching to Trash', async () => {
  let resolve: (value: unknown) => void = () => {};
  stubFetch({
    [`GET ${API}`]: (call: Call) =>
      call.url.endsWith('false')
        ? new Promise((r) => {
            resolve = r;
          })
        : [calendar({ name: 'Deleted' })],
  });
  const view = await mount(<Probe />);
  await flush();
  await click(view.button('Trash'));
  await flush();
  resolve([calendar({ name: 'Active calendar' })]);
  await flush();
  expect(view.host.textContent).toContain('Deleted');
  expect(view.host.textContent).not.toContain('Active calendar');
  await view.unmount();
});
it('reloads after a mutation without changing the filter', async () => {
  let count = 0;
  const calls = stubFetch({
    [`GET ${API}`]: () => [calendar({ name: ++count === 1 ? 'Before' : 'After' })],
  });
  const view = await mount(<Probe />);
  await flush();
  await click(view.button('Reload'));
  await flush();
  expect(view.host.textContent).toContain('After');
  expect(calls.map((c) => c.url)).toEqual([`${API}?trashed=false`, `${API}?trashed=false`]);
  await view.unmount();
});
