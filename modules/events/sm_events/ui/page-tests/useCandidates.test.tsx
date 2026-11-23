// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import type { Call } from './support';
import { flush, stubFetch } from './support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { useCandidates } = await import('../hooks/useCandidates');
const path = '/api/events/calendars/c1/share-candidates';
function Probe({ query, open = true }: { query: string; open?: boolean }) {
  const state = useCandidates('c1', open, query);
  return (
    <div>
      {state.candidates.map((c) => (
        <span key={c.id}>{c.display_name}</span>
      ))}
      {state.error}
    </div>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});
it('does not search while closed or below three trimmed code points', async () => {
  const calls = stubFetch({ [`GET ${path}`]: [] });
  const view = await mount(<Probe query="ab" />);
  await flush(300);
  expect(calls).toHaveLength(0);
  await view.render(<Probe query="sam" open={false} />);
  await flush(300);
  expect(calls).toHaveLength(0);
  await view.render(<Probe query=" sam " />);
  await flush(300);
  expect(calls.map((c) => c.url)).toEqual([`${path}?q=sam`]);
  await view.unmount();
});
it('ignores a late result for a previous query', async () => {
  let resolve: (value: unknown) => void = () => {};
  stubFetch({
    [`GET ${path}`]: (call: Call) =>
      call.url.endsWith('sam')
        ? new Promise((r) => {
            resolve = r;
          })
        : [{ id: 'u3', display_name: 'Kim', email: 'k***@example.org' }],
  });
  const view = await mount(<Probe query="sam" />);
  await flush(300);
  await view.render(<Probe query="kim" />);
  await flush(300);
  resolve([{ id: 'u2', display_name: 'Sam', email: 's***@example.org' }]);
  await flush();
  expect(view.host.textContent).toBe('Kim');
  await view.unmount();
});
