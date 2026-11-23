// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { calendar, flush, stubFetch } from './support';
import { mount } from './test-dom';

const auth = vi.hoisted(() => ({ permissions: [] as string[] }));
vi.mock('@inertiajs/react', async () => ({
  ...(await import('./support')).inertiaMock(),
  usePage: () => ({ props: { auth } }),
}));
const { default: Calendars } = await import('../../pages/Calendars');

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

it.each([false, true])('offers Share only with sharing.share: %s', async (allowed) => {
  auth.permissions = allowed ? ['events.view', 'sharing.share'] : ['events.view'];
  stubFetch({ 'GET /api/events/calendars': [calendar()] });
  const view = await mount(
    <Calendars can_create={false} can_manage={false} user_id="u1" default_timezone="UTC" />,
  );
  try {
    await flush();
    expect(view.button('Share') !== undefined).toBe(allowed);
    expect(view.button('Move to trash')).toBeDefined();
  } finally {
    await view.unmount();
  }
});
