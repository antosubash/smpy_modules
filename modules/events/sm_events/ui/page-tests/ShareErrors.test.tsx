// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { ShareDialog } = await import('../components/share/ShareDialog');
const { OwnerDialog } = await import('../components/calendars/OwnerDialog');

const SHARES = '/api/sharing/shares';
const CANDIDATES = '/api/events/calendars/c1/share-candidates';
const sam = { id: 'u2', display_name: 'Sam Smith', email: 's***@example.com' };

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

const limited = (retry?: number) =>
  Response.json(
    { detail: 'Too many requests', ...(retry ? { retry_after: retry } : {}) },
    { status: 429, headers: retry ? { 'Retry-After': String(retry) } : {} },
  );
const dialog = () => document.querySelector('[role="dialog"]')?.textContent ?? '';

async function openShare(candidates: unknown, onGone = vi.fn()) {
  stubFetch({ [`GET ${SHARES}`]: [], [`GET ${CANDIDATES}`]: candidates });
  const view = await mount(<ShareDialog calendarId="c1" calendarName="Team" onGone={onGone} />);
  await click(view.find('[data-testid="events-share"]'));
  await flush(300);
  const input = document.querySelector<HTMLInputElement>('#events-share-search');
  if (input) await setValue(input, 'sam');
  await flush(300);
  return view;
}

describe('picker rate limit', () => {
  it('shows the wait, no empty state and no results on a 429 with retry_after', async () => {
    const view = await openShare(limited(7));
    expect(dialog()).toContain('Too many searches. Try again in 7 seconds.');
    expect(dialog()).not.toContain('No one found.');
    expect(dialog()).not.toContain('The request failed');
    await view.unmount();
  });
  it('says "in a moment" without a retry value', async () => {
    const view = await openShare(limited());
    expect(dialog()).toContain('Try again in a moment.');
    expect(dialog()).not.toContain('No one found.');
    await view.unmount();
  });
  it('does not show the empty-state text for any error, and drops earlier results', async () => {
    let fail = false;
    stubFetch({
      [`GET ${SHARES}`]: [],
      [`GET ${CANDIDATES}`]: () => (fail ? Response.json({}, { status: 500 }) : [sam]),
    });
    const view = await mount(<ShareDialog calendarId="c1" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    const input = document.querySelector<HTMLInputElement>('#events-share-search');
    if (!input) throw new Error('no input');
    await setValue(input, 'sam');
    await flush(300);
    expect(dialog()).toContain('Sam Smith');
    fail = true;
    await setValue(input, 'samu');
    await flush(300);
    expect(dialog()).not.toContain('Sam Smith');
    expect(dialog()).not.toContain('No one found.');
    expect(dialog()).toContain('The request failed.');
    await view.unmount();
  });
  it('names the picker buttons after the person', async () => {
    const view = await openShare([sam]);
    const grant = document.querySelector('[data-testid="events-share-candidate"] button');
    expect(grant?.getAttribute('aria-label')).toBe('Share with Sam Smith');
    expect(view.find('[data-testid="events-share"]')?.getAttribute('aria-label')).toBe(
      'Share Team',
    );
    await view.unmount();
  });
  it('gives the ownership dialog the same 429 message', async () => {
    stubFetch({ [`GET ${CANDIDATES}`]: limited(3) });
    const view = await mount(<OwnerDialog calendarId="c1" calendarName="Team" onSaved={vi.fn()} />);
    await click(view.button('Transfer ownership'));
    const input = document.querySelector<HTMLInputElement>('#owner-search');
    if (!input) throw new Error('no input');
    await setValue(input, 'sam');
    await flush(300);
    expect(dialog()).toContain('Try again in 3 seconds.');
    await view.unmount();
  });
});

describe('reopening a dialog', () => {
  it('shows no rate-limit message before a new search (share and transfer)', async () => {
    stubFetch({ [`GET ${SHARES}`]: [], [`GET ${CANDIDATES}`]: limited(7) });
    const view = await mount(<ShareDialog calendarId="c1" calendarName="Team" />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    const input = document.querySelector<HTMLInputElement>('#events-share-search');
    if (!input) throw new Error('no input');
    await setValue(input, 'sam');
    await flush(300);
    expect(dialog()).toContain('Too many searches');
    await click(document.querySelector('[role="dialog"] button:last-of-type'));
    await flush(300);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    expect(dialog()).not.toContain('Too many searches');
    expect(document.querySelector<HTMLInputElement>('#events-share-search')?.value).toBe('');
    await view.unmount();
  });
  it('clears the transfer dialog on reopen: query, choice and rate-limit message', async () => {
    stubFetch({
      [`GET ${CANDIDATES}`]: (call: { url: string }) =>
        call.url.endsWith('=sam') ? [sam] : limited(3),
    });
    const view = await mount(<OwnerDialog calendarId="c1" calendarName="Team" onSaved={vi.fn()} />);
    await click(view.button('Transfer ownership'));
    const input = () => document.querySelector<HTMLInputElement>('#owner-search');
    const cancel = () =>
      [...document.querySelectorAll('[role="dialog"] button')].find(
        (b) => b.textContent === 'Cancel',
      );
    const submitButton = () =>
      [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(
        (b) => b.textContent === 'Transfer ownership',
      );
    await setValue(input() as HTMLInputElement, 'sam');
    await flush(300);
    await click(document.querySelector('[aria-pressed]'));
    expect(dialog()).toContain('Sam Smith');
    expect(submitButton()?.disabled).toBe(false);
    await setValue(input() as HTMLInputElement, 'samu');
    await flush(300);
    expect(dialog()).toContain('Try again in 3 seconds.');
    await click(cancel());
    await flush(300);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await click(view.button('Transfer ownership'));
    await flush(300);
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(input()?.value).toBe('');
    expect(dialog()).not.toContain('Try again');
    expect(dialog()).not.toContain('New owner');
    expect(submitButton()?.disabled).toBe(true);
    await view.unmount();
  });
});

describe('calendar gone', () => {
  it('shows "no longer exists", not "Not shared yet", and refreshes the list', async () => {
    const onGone = vi.fn();
    stubFetch({ [`GET ${SHARES}`]: Response.json({ detail: 'Not found' }, { status: 404 }) });
    const view = await mount(<ShareDialog calendarId="c1" onGone={onGone} />);
    await click(view.find('[data-testid="events-share"]'));
    await flush(300);
    expect(dialog()).toContain('This calendar no longer exists.');
    expect(dialog()).not.toContain('Not shared with anyone yet.');
    expect(onGone).toHaveBeenCalled();
    await view.unmount();
  });
  it('says so in the transfer dialog and refreshes the list', async () => {
    const onSaved = vi.fn();
    stubFetch({
      [`GET ${CANDIDATES}`]: [sam],
      'PUT /api/events/calendars/c1/owner': Response.json({ detail: 'x' }, { status: 404 }),
    });
    const view = await mount(<OwnerDialog calendarId="c1" calendarName="Team" onSaved={onSaved} />);
    await click(view.button('Transfer ownership'));
    const input = document.querySelector<HTMLInputElement>('#owner-search');
    if (!input) throw new Error('no input');
    await setValue(input, 'sam');
    await flush(300);
    await click(view.button('Select Sam Smith') ?? document.querySelector('[aria-pressed]'));
    const form = document.querySelector('[role="dialog"] form');
    const { act } = await import('./test-dom');
    await act(async () => {
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(dialog()).toContain('This calendar no longer exists.');
    expect(onSaved).toHaveBeenCalled();
    await view.unmount();
  });
});
