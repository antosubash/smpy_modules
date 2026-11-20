// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { click, mount, settle } from './test-dom';

vi.mock('@inertiajs/react', () => ({ Head: () => null }));
vi.mock('@simple-module-py/ui/components/PageShell', () => ({
  PageShell: ({ children }: { children: unknown }) => <main>{children as never}</main>,
}));
vi.mock('../components/RecordsLayout', () => ({ RecordsLayout: () => null }));
vi.mock('../utils/my-registrations-api', () => ({ listMine: vi.fn(), cancelMine: vi.fn() }));
const api = await import('../utils/my-registrations-api');
const MyRegistrations = (await import('../../pages/MyRegistrations')).default;

const item = (uuid: string, status: 'pending' | 'registered' = 'registered') => ({
  uuid,
  type_key: 'regs',
  status,
  event_id: 'e',
  occurrence_key: 'e',
  title: `Event ${uuid}`,
  when_text: 'Wed 1 Jul, 10:00',
  page_path: '/events/x',
  starts_at: null,
  available: true,
});
const text = () => document.body.textContent ?? '';
beforeEach(() =>
  vi
    .mocked(api.listMine)
    .mockResolvedValue({ verified: true, items: [item('a'), item('b', 'pending')] }),
);
afterEach(() => {
  document.body.innerHTML = '';
  vi.clearAllMocks();
});

it('lists registrations with their state', async () => {
  const v = await mount(<MyRegistrations />);
  await settle();
  expect(v.all('[data-testid=mine-item]')).toHaveLength(2);
  expect(text()).toContain('Registered');
  expect(text()).toContain('Waiting for your confirmation');
  expect(text()).toContain('Wed 1 Jul, 10:00');
  await v.unmount();
});

it('shows an empty state, and an unverified notice instead of a list', async () => {
  vi.mocked(api.listMine).mockResolvedValue({ verified: true, items: [] });
  const a = await mount(<MyRegistrations />);
  await settle();
  expect(a.find('[data-testid=mine-empty]')).not.toBeNull();
  await a.unmount();
  vi.mocked(api.listMine).mockResolvedValue({ verified: false, items: [] });
  const b = await mount(<MyRegistrations />);
  await settle();
  expect(b.find('[data-testid=mine-unverified]')?.textContent).toContain('not verified');
  expect(b.find('[data-testid=mine-list]')).toBeNull();
  await b.unmount();
});

it('asks before cancelling, then cancels and shows the rest', async () => {
  vi.mocked(api.cancelMine).mockResolvedValue({ verified: true, items: [item('b', 'pending')] });
  const v = await mount(<MyRegistrations />);
  await settle();
  await click(v.button('Cancel registration'));
  expect(api.cancelMine).not.toHaveBeenCalled();
  expect(text()).toContain('Your seat goes to someone else');
  await click(v.button('Yes, cancel'));
  await settle();
  expect(api.cancelMine).toHaveBeenCalledWith('a');
  expect(v.all('[data-testid=mine-item]')).toHaveLength(1);
  expect(text()).toContain('Registration cancelled');
  await v.unmount();
});

it('keeping it changes nothing, and a failed cancel says so', async () => {
  const v = await mount(<MyRegistrations />);
  await settle();
  await click(v.button('Cancel registration'));
  await click(v.button('Keep it'));
  expect(api.cancelMine).not.toHaveBeenCalled();
  vi.mocked(api.cancelMine).mockRejectedValue(new Error('x'));
  await click(v.button('Cancel registration'));
  await click(v.button('Yes, cancel'));
  await settle();
  expect(v.find('[role=alert]')?.textContent).toContain('could not be cancelled');
  expect(v.all('[data-testid=mine-item]')).toHaveLength(2);
  await v.unmount();
});

it('a failed load can be retried', async () => {
  vi.mocked(api.listMine).mockRejectedValueOnce(new Error('x'));
  const v = await mount(<MyRegistrations />);
  await settle();
  expect(v.find('[role=alert]')?.textContent).toContain('could not be loaded');
  await click(v.button('Try again'));
  await settle();
  expect(v.all('[data-testid=mine-item]')).toHaveLength(2);
  await v.unmount();
});

it('a row whose event is gone says so and offers no cancel', async () => {
  vi.mocked(api.listMine).mockResolvedValue({
    verified: true,
    items: [{ ...item('g'), available: false, when_text: null, page_path: null }],
  });
  const v = await mount(<MyRegistrations />);
  await settle();
  expect(text()).toContain('This event is no longer available');
  expect(v.button('Cancel registration')).toBeUndefined();
  expect(text()).not.toContain('Event g');
  expect(text()).not.toContain('Registered'); // the status badge gives way to the unavailable state
  await v.unmount();
});
