// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { ShareDialog } = await import('../components/share/ShareDialog');
const { OwnerDialog } = await import('../components/calendars/OwnerDialog');

const SHARES = '/api/sharing/shares';
const CANDIDATES = '/api/events/calendars/c1/share-candidates';
const missing = () => Response.json({ detail: 'Not found' }, { status: 404 });
const limited = () => Response.json({ detail: 'slow down', retry_after: 7 }, { status: 429 });
const dialog = () => document.querySelector('[role="dialog"]')?.textContent ?? '';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function type(selector: string, value: string) {
  const input = document.querySelector<HTMLInputElement>(selector);
  if (!input) throw new Error(`no ${selector}`);
  await setValue(input, value);
  await flush(300);
}

describe('a request cannot outlive its dialog', () => {
  it('ignores the 404 of a Retry that started before the dialog was closed and reopened', async () => {
    const onGone = vi.fn();
    let reads = 0;
    let rejectOld: (r: Response) => void = () => {};
    stubFetch({
      [`GET ${SHARES}`]: () => {
        reads += 1;
        if (reads === 1) return Response.json({}, { status: 500 });
        if (reads === 2) return new Promise<Response>((r) => (rejectOld = r));
        return [];
      },
      [`GET ${CANDIDATES}`]: [],
    });
    const view = await mount(<ShareDialog calendarId="c1" onGone={onGone} />);
    await click(view.find('[data-testid="events-share"]'));
    await flush();
    await click(document.querySelector('[data-testid="events-share-list-error"] button'));
    await flush();
    await click(document.querySelector('[role="dialog"] button:last-of-type'));
    await flush();
    await click(view.find('[data-testid="events-share"]'));
    await flush();
    expect(dialog()).toContain('Not shared with anyone yet.');
    rejectOld(missing());
    await flush();
    expect(dialog()).toContain('Not shared with anyone yet.');
    expect(dialog()).not.toContain('no longer exists');
    expect(onGone).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('calls onGone once when the grants list and the picker both answer 404', async () => {
    const onGone = vi.fn();
    stubFetch({ [`GET ${SHARES}`]: missing(), [`GET ${CANDIDATES}`]: missing() });
    const view = await mount(<ShareDialog calendarId="c1" onGone={onGone} />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    await type('#events-share-search', 'sam');
    expect(dialog()).toContain('This calendar no longer exists.');
    expect(onGone).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('never calls onGone from a request that finishes after the dialog unmounted', async () => {
    const onGone = vi.fn();
    let answer: (r: Response) => void = () => {};
    stubFetch({
      [`GET ${SHARES}`]: [],
      [`POST ${SHARES}`]: () => new Promise<Response>((r) => (answer = r)),
      [`GET ${CANDIDATES}`]: [{ id: 'u2', display_name: 'Sam Smith', email: 's***@e.com' }],
    });
    const view = await mount(<ShareDialog calendarId="c1" onGone={onGone} />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    await type('#events-share-search', 'sam');
    await click(document.querySelector('[data-testid="events-share-candidate"] button'));
    await view.unmount();
    answer(missing());
    await flush();
    expect(onGone).not.toHaveBeenCalled();
  });

  it('keeps the rate-limit wait visible when the query shrinks below the minimum', async () => {
    stubFetch({ [`GET ${SHARES}`]: [], [`GET ${CANDIDATES}`]: limited() });
    const view = await mount(<ShareDialog calendarId="c1" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    await type('#events-share-search', 'sam');
    expect(dialog()).toContain('Try again in 7 seconds.');
    await type('#events-share-search', 'sa');
    expect(dialog()).toContain('Try again in 7 seconds.');
    await view.unmount();
  });

  it('calls onSaved once when a failed transfer and a picker 404 both find the calendar gone', async () => {
    const onSaved = vi.fn();
    let searches = 0;
    stubFetch({
      [`GET ${CANDIDATES}`]: () => {
        searches += 1;
        return searches === 1
          ? [{ id: 'u2', display_name: 'Sam Smith', email: 's***@e.com' }]
          : missing();
      },
      'PUT /api/events/calendars/c1/owner': missing(),
    });
    const view = await mount(<OwnerDialog calendarId="c1" calendarName="Team" onSaved={onSaved} />);
    await click(view.button('Transfer ownership'));
    await type('#owner-search', 'sam');
    await click(view.button('Select Sam Smith') ?? document.querySelector('[aria-pressed]'));
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(onSaved).toHaveBeenCalledTimes(1);
    await type('#owner-search', 'samu');
    expect(searches).toBeGreaterThan(1);
    expect(onSaved).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('calls onSaved once when the picker 404s', async () => {
    const onSaved = vi.fn();
    stubFetch({ [`GET ${CANDIDATES}`]: missing() });
    const view = await mount(<OwnerDialog calendarId="c1" calendarName="Team" onSaved={onSaved} />);
    await click(view.button('Transfer ownership'));
    await type('#owner-search', 'sam');
    await type('#owner-search', 'samu');
    expect(onSaved).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
