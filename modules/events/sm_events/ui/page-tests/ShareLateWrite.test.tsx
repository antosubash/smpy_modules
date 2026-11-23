// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));
const { ShareDialog } = await import('../components/share/ShareDialog');

const SHARES = '/api/sharing/shares';
const CANDIDATES = '/api/events/calendars/c1/share-candidates';
const sam = { id: 'u2', display_name: 'Sam Smith', email: 's***@e.com' };
const granted = {
  id: 's9',
  subject_id: 'u2',
  subject_label: 'Sam Smith',
  role: 'view',
  expired: false,
};
const dialog = () => document.querySelector('[role="dialog"]')?.textContent ?? '';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  toast.mockClear();
});

async function startGrant(committed: { value: boolean }, answer: { send: () => void }) {
  const calls = stubFetch({
    [`GET ${SHARES}`]: () => (committed.value ? [granted] : []),
    [`POST ${SHARES}`]: () =>
      new Promise<Response>((resolve) => {
        answer.send = () => {
          committed.value = true;
          resolve(Response.json(granted, { status: 201 }));
        };
      }),
    [`GET ${CANDIDATES}`]: [sam],
  });
  const view = await mount(<ShareDialog calendarId="c1" />);
  await click(view.find('[data-testid="events-share"]'));
  await flush(300);
  const input = document.querySelector<HTMLInputElement>('#events-share-search');
  if (input) await setValue(input, 'sam');
  await flush(300);
  await click(document.querySelector('[data-testid="events-share-candidate"] button'));
  const buttons = [...document.querySelectorAll('[role="dialog"] button')];
  await click(buttons.find((b) => b.textContent === 'Close') ?? null);
  await flush();
  return { calls, view };
}

const reads = (calls: { url: string; method?: string }[]) =>
  calls.filter((c) => c.url.startsWith(SHARES) && (c.method ?? 'GET') === 'GET').length;

describe('a grant that outlives its dialog', () => {
  it('shows after reopening when the reopen read finished before the write committed', async () => {
    const committed = { value: false };
    const answer = { send: () => {} };
    const { view } = await startGrant(committed, answer);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    expect(dialog()).toContain('Not shared with anyone yet.');
    answer.send();
    await flush(300);
    expect(dialog()).toContain('Sam Smith');
    expect(toast).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('does nothing when it completes while no dialog is open', async () => {
    const committed = { value: false };
    const answer = { send: () => {} };
    const { calls, view } = await startGrant(committed, answer);
    const before = reads(calls);
    answer.send();
    await flush(300);
    expect(reads(calls)).toBe(before);
    expect(toast).not.toHaveBeenCalled();
    await view.unmount();
  });
});
