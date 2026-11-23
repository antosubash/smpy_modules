// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { useShares } = await import('../hooks/useShares');
const SHARES = '/api/sharing/shares';
function Probe({ open = true }: { open?: boolean }) {
  const state = useShares('c1', open);
  return (
    <div>
      {state.shares.map((s) => (
        <span key={s.id}>{s.subject_label}</span>
      ))}
      <button
        type="button"
        onClick={() =>
          void state.grant({ id: 'u2', display_name: 'Sam', email: 's***@example.org' }, 'view')
        }
      >
        Grant
      </button>
    </div>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});
it('does not overwrite a grant refresh with an older list on reopening', async () => {
  let resolveOld: (value: unknown) => void = () => {};
  let reads = 0;
  const share = { id: 's1', subject_id: 'u2', subject_label: 'Sam', role: 'view', expired: false };
  stubFetch({
    [`GET ${SHARES}`]: () =>
      ++reads === 1
        ? new Promise((r) => {
            resolveOld = r;
          })
        : reads === 2
          ? []
          : [share],
    [`POST ${SHARES}`]: share,
  });
  const view = await mount(<Probe />);
  await flush();
  await view.render(<Probe open={false} />);
  await view.render(<Probe />);
  await flush();
  await click(view.button('Grant'));
  await flush();
  expect(view.host.textContent).toContain('Sam');
  resolveOld([]);
  await flush();
  expect(view.host.textContent).toContain('Sam');
  await view.unmount();
});
