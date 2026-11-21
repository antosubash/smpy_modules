// @vitest-environment happy-dom
import { lazy } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, mount } from '../page-tests/test-dom';
import { PluginBoundary } from './PluginBoundary';

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

function Boom(): never {
  throw new Error('secret payload');
}

it('a render error falls back, is logged once by name and never shows its message', async () => {
  const error = vi.spyOn(console, 'error').mockImplementation(() => {});
  const view = await mount(
    <PluginBoundary name="acme:chip" fallback={<i data-testid="fallback">plain</i>}>
      <Boom />
    </PluginBoundary>,
  );
  expect(view.find('[data-testid="fallback"]')).not.toBeNull();
  const ours = error.mock.calls.filter((c) => String(c[0]).includes('acme:chip'));
  expect(ours).toHaveLength(1);
  expect(JSON.stringify(ours)).not.toContain('secret payload');
  await view.unmount();
});

it('a rejected lazy import falls back', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const Broken = lazy(() => Promise.reject(new Error('chunk missing')));
  const view = await mount(
    <PluginBoundary name="acme:late" fallback={<i data-testid="fallback">plain</i>}>
      <Broken />
    </PluginBoundary>,
  );
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
  expect(view.find('[data-testid="fallback"]')).not.toBeNull();
  await view.unmount();
});

it('renders the child while it loads and when it works', async () => {
  const Fine = lazy(async () => ({ default: () => <b data-testid="fine">ok</b> }));
  const view = await mount(
    <PluginBoundary name="acme:ok" fallback={<i data-testid="fallback" />}>
      <Fine />
    </PluginBoundary>,
  );
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
  expect(view.find('[data-testid="fine"]')).not.toBeNull();
  expect(view.find('[data-testid="fallback"]')).toBeNull();
  await view.unmount();
});

it('a failure does not reach a sibling boundary', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const view = await mount(
    <div>
      <PluginBoundary name="a" fallback={<i data-testid="fa" />}>
        <Boom />
      </PluginBoundary>
      <PluginBoundary name="b" fallback={null}>
        <b data-testid="b">fine</b>
      </PluginBoundary>
    </div>,
  );
  expect(view.find('[data-testid="fa"]')).not.toBeNull();
  expect(view.find('[data-testid="b"]')).not.toBeNull();
  await view.unmount();
});
