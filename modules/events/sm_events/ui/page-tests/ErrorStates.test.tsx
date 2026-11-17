// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, calendar, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { toast } = await import('sonner');
const { default: Calendars } = await import('../../pages/Calendars');
const { default: Categories } = await import('../../pages/Categories');
const { ShareDialog } = await import('../components/share/ShareDialog');
const API = '/api/events/calendars';
const CATS = '/api/events/categories';
const SHARES = '/api/sharing/shares';
const CANDIDATES = `${API}/c1/share-candidates`;
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };
const GONE = 'This calendar no longer exists.';
const share = { id: 's1', subject_id: 'u2', subject_label: 'Sam', role: 'view', expired: false };
const sam = { id: 'u3', display_name: 'Sam Smith', email: 's***@example.com' };

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(toast.error).mockClear();
  document.body.innerHTML = '';
});

const dialog = () => document.querySelector('[role="dialog"]')?.textContent ?? '';
const invalid = (status: number, detail: unknown) => Response.json({ detail }, { status });
const unprocessable = (...locs: string[][]) =>
  invalid(
    422,
    locs.map((loc) => ({ loc: ['body', ...loc], msg: 'bad' })),
  );

describe('422 entries', () => {
  it('shows the generic message when an entry maps to no shown field', async () => {
    stubFetch({ [`GET ${API}`]: [calendar()], [`PATCH ${API}/c1`]: unprocessable(['sources']) });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await submit();
    expect(dialog()).toContain('Check the fields and try again.');
    await view.unmount();
  });
  it('shows the mapped field and the generic message when only some entries map', async () => {
    stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: unprocessable(['default_timezone'], ['sources']),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await submit();
    expect(document.getElementById('calendar-timezone-error')?.textContent).toContain(
      'Choose a timezone',
    );
    expect(dialog()).toContain('Check the fields and try again.');
    await view.unmount();
  });
  it('sends a timezone the browser list lacks and lets the server decide', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: [],
      [`POST ${API}`]: unprocessable(['default_timezone']),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    await setValue(field('calendar-name'), 'Team');
    await setValue(field('calendar-timezone'), 'Mars/Phobos');
    await submit();
    expect(calls.some((c) => c.method === 'POST')).toBe(true);
    expect(document.getElementById('calendar-timezone-error')?.textContent).toContain(
      'Choose a timezone',
    );
    expect(dialog()).not.toContain('Check the fields');
    await view.unmount();
  });
  it('marks only the locale input the path names, and the group for the whole map', async () => {
    let body = unprocessable(['names', 'de']);
    stubFetch({ [`GET ${CATS}`]: [], [`POST ${CATS}`]: () => body });
    const view = await mount(<Categories content_locales={['en', 'de']} />);
    await flush();
    await click(button('New category'));
    await setValue(field('category-name-en'), 'Music');
    await submit();
    expect(field('category-name-de').getAttribute('aria-invalid')).toBe('true');
    expect(field('category-name-en').getAttribute('aria-invalid')).toBeNull();
    body = unprocessable(['names']);
    await submit();
    expect(field('category-name-de').getAttribute('aria-invalid')).toBeNull();
    expect(field('category-name-en').getAttribute('aria-invalid')).toBeNull();
    expect(document.getElementById('category-names-error')?.textContent).toContain('Enter names');
    for (const id of ['category-name-en', 'category-name-de']) {
      expect(field(id).getAttribute('aria-describedby')).toBe('category-names-error');
    }
    const group = document.getElementById('category-names-error')?.closest('fieldset');
    expect(group?.getAttribute('aria-invalid')).toBe('true');
    expect(group?.getAttribute('aria-describedby')).toBe('category-names-error');
    body = unprocessable(['names', 'de']);
    await submit();
    expect(field('category-name-de').getAttribute('aria-describedby')).toBe(
      'category-name-de-error',
    );
    await view.unmount();
  });
});

describe('a 404 in the share dialog', () => {
  async function open(routes: Record<string, unknown>, onGone = vi.fn()) {
    stubFetch(routes);
    const view = await mount(<ShareDialog calendarId="c1" calendarName="Team" onGone={onGone} />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    return { view, onGone };
  }
  it('is no error when the grant was already revoked elsewhere; the stale row goes', async () => {
    let reads = 0;
    const { view, onGone } = await open({
      [`GET ${SHARES}`]: () => (++reads === 1 ? [share] : []),
      [`GET ${CANDIDATES}`]: [],
      [`DELETE ${SHARES}/s1`]: invalid(404, 'Not found'),
    });
    expect(dialog()).toContain('Sam');
    await click(document.querySelector('[aria-label="Remove access for Sam"]'));
    await flush();
    expect(dialog()).not.toContain(GONE);
    expect(dialog()).not.toContain('Sam ·');
    expect(toast.error).not.toHaveBeenCalled();
    expect(onGone).not.toHaveBeenCalled();
    await view.unmount();
  });
  it('says the calendar is gone, and refreshes, when granting for it 404s', async () => {
    const { view, onGone } = await open({
      [`GET ${SHARES}`]: [],
      [`GET ${CANDIDATES}`]: [sam],
      [`POST ${SHARES}`]: invalid(404, 'Not found'),
    });
    await setValue(
      document.querySelector<HTMLInputElement>('#events-share-search') as HTMLInputElement,
      'sam',
    );
    await flush(300);
    await click(document.querySelector('[aria-label="Share with Sam Smith"]'));
    await flush();
    expect(toast.error).toHaveBeenCalledWith(GONE);
    expect(onGone).toHaveBeenCalled();
    await view.unmount();
  });
  it('says so, and refreshes, when the picker search 404s', async () => {
    const { view, onGone } = await open({
      [`GET ${SHARES}`]: [],
      [`GET ${CANDIDATES}`]: invalid(404, 'Not found'),
    });
    await setValue(
      document.querySelector<HTMLInputElement>('#events-share-search') as HTMLInputElement,
      'sam',
    );
    await flush(300);
    expect(dialog()).toContain(GONE);
    expect(onGone).toHaveBeenCalled();
    await view.unmount();
  });
});

describe('independent grants and picker state', () => {
  it('keeps searching after the grants failed to load, and Retry reloads them', async () => {
    let reads = 0;
    stubFetch({
      [`GET ${SHARES}`]: () => (++reads === 1 ? invalid(500, 'x') : [share]),
      [`GET ${CANDIDATES}`]: [sam],
    });
    const view = await mount(<ShareDialog calendarId="c1" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    const area = () => document.querySelector('[data-testid="events-share-list-error"]');
    expect(area()?.textContent).toContain('The request failed.');
    await setValue(
      document.querySelector<HTMLInputElement>('#events-share-search') as HTMLInputElement,
      'sam',
    );
    await flush(300);
    expect(dialog()).toContain('Sam Smith');
    await click(area()?.querySelector('button') ?? null);
    await flush();
    expect(area()).toBeNull();
    expect(dialog()).toContain('Sam ·');
    await view.unmount();
  });
});

describe('after a 429', () => {
  it('keeps the wait message, never the empty state, until the next response', async () => {
    let release: (value: unknown) => void = () => {};
    const limited = Response.json({ detail: 'x', retry_after: 7 }, { status: 429 });
    stubFetch({
      [`GET ${SHARES}`]: [],
      [`GET ${CANDIDATES}`]: (call: { url: string }) =>
        call.url.endsWith('sam')
          ? limited
          : new Promise((r) => {
              release = r;
            }),
    });
    const view = await mount(<ShareDialog calendarId="c1" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    const input = document.querySelector<HTMLInputElement>(
      '#events-share-search',
    ) as HTMLInputElement;
    await setValue(input, 'sam');
    await flush(300);
    expect(dialog()).toContain('Try again in 7 seconds.');
    await setValue(input, 'samu');
    expect(dialog()).toContain('Try again in 7 seconds.');
    expect(dialog()).not.toContain('No one found.');
    await flush(300);
    expect(dialog()).toContain('Try again in 7 seconds.');
    expect(dialog()).not.toContain('No one found.');
    release([]);
    await flush();
    expect(dialog()).not.toContain('Try again');
    expect(dialog()).toContain('No one found.');
    await view.unmount();
  });
  it('shows no empty state before the first answer arrives', async () => {
    stubFetch({ [`GET ${SHARES}`]: [], [`GET ${CANDIDATES}`]: () => new Promise(() => {}) });
    const view = await mount(<ShareDialog calendarId="c1" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    await setValue(
      document.querySelector<HTMLInputElement>('#events-share-search') as HTMLInputElement,
      'sam',
    );
    await flush(300);
    expect(dialog()).not.toContain('No one found.');
    await view.unmount();
  });
});
