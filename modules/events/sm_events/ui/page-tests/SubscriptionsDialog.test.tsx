// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, dialog, LIST, open, sub, text } from './subscriptions-dialog-support';
import { calendar, flush } from './support';
import { click, press, setValue } from './test-dom';

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

describe('SubscriptionsDialog', () => {
  it('adds a subscription and clears the address field', async () => {
    let made = false;
    const { calls, view } = await open({
      [`GET ${LIST}`]: () => (made ? [sub()] : []),
      [`POST ${LIST}`]: () => {
        made = true;
        return Response.json(sub(), { status: 201 });
      },
    });
    await click(button('Add a subscription') as HTMLElement);
    const url = document.getElementById('events-sub-url') as HTMLInputElement;
    expect(url.type).toBe('url');
    expect(url.autocomplete).toBe('off');
    expect(text()).toContain('stored encrypted and never shown again');
    await setValue(url, 'https://feeds.example.test/private/SECRET/basic.ics');
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'Holidays');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toMatchObject({
      url: 'https://feeds.example.test/private/SECRET/basic.ics',
      label: 'Holidays',
      public: false,
    });
    expect(document.getElementById('events-sub-url')).toBeNull(); // the form closed
    expect(text()).not.toContain('SECRET'); // and nothing shows the address again
    await view.unmount();
  });

  it('edit leaves the address empty and omits it from the patch unless typed', async () => {
    const { calls, view } = await open({
      [`GET ${LIST}`]: [sub()],
      'PATCH /api/events/subscriptions/s1': () => Response.json(sub({ label: 'Renamed' })),
    });
    await click(button('Edit') as HTMLElement);
    const url = document.getElementById('events-sub-url') as HTMLInputElement;
    expect(url.value).toBe('');
    expect(url.placeholder).toContain('Leave empty to keep the current address');
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'Renamed');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.body).toEqual({ expected: 'v1', label: 'Renamed' });
    await view.unmount();
  });

  it('the public toggle needs a public calendar and the publish permission', async () => {
    const cases: [boolean, string, boolean][] = [
      [false, 'public', true],
      [true, 'private', true],
      [true, 'public', false],
    ];
    for (const [canPublish, visibility, disabled] of cases) {
      const { view } = await open(
        { [`GET ${LIST}`]: [] },
        { canPublish, calendar: calendar({ visibility }) },
      );
      await click(button('Add a subscription') as HTMLElement);
      const box = document.getElementById('events-sub-public') as HTMLInputElement;
      expect(box.disabled, `${canPublish} ${visibility}`).toBe(disabled);
      await view.unmount();
      document.body.innerHTML = '';
    }
  });

  const room = (calendar: number, owner = 1, tenant = 1) => ({
    calendar: { used: calendar, limit: 10 },
    owner: { used: owner, limit: 30 },
    tenant: { used: tenant, limit: 100 },
  });

  it('keeps Add off, with the reason, when an allowance is used up', async () => {
    const cases: [ReturnType<typeof room>, string][] = [
      [room(10), 'This calendar has the maximum of 10 subscriptions.'],
      [room(2, 30), 'You have added the maximum of 30 subscriptions.'],
      [room(2, 3, 100), 'This organisation has the maximum of 100 subscriptions.'],
    ];
    for (const [capacity, reason] of cases) {
      const { view } = await open({
        [`GET ${LIST}`]: [sub()],
        [`GET ${LIST}/capacity`]: capacity,
      });
      const add = button('Add a subscription') as HTMLButtonElement;
      expect(add.disabled).toBe(true);
      expect(text()).toContain(reason);
      expect(add.getAttribute('aria-describedby')).toBe('events-sub-full');
      await view.unmount();
      document.body.innerHTML = '';
    }
    const { view } = await open({ [`GET ${LIST}`]: [], [`GET ${LIST}/capacity`]: room(2) });
    expect((button('Add a subscription') as HTMLButtonElement).disabled).toBe(false);
    await view.unmount();
  });

  it('drops a stale refusal as soon as the person types again', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [],
      [`POST ${LIST}`]: () =>
        Response.json({ detail: 'x', code: 'subscription_exists' }, { status: 409 }),
    });
    await click(button('Add a subscription') as HTMLElement);
    const url = document.getElementById('events-sub-url') as HTMLInputElement;
    await setValue(url, 'https://a.example/x.ics');
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'A');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const refusal = () =>
      document.querySelector('[data-testid="subscription-form"] [role="alert"]');
    expect(refusal()).not.toBeNull();
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'AB');
    expect(refusal()).toBeNull(); // typing clears it
    await click(button('Save') as HTMLElement);
    await flush(50);
    expect(refusal()).not.toBeNull();
    await view.unmount();
  });

  it('returns focus to the control that opened the form when it closes', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [sub()] });
    await click(button('Add a subscription') as HTMLElement);
    await flush(20);
    await press(dialog(), { key: 'Escape' });
    await flush(30);
    expect(document.activeElement).toBe(button('Add a subscription'));
    const edit = [...document.querySelectorAll('button')].find((b) =>
      b.getAttribute('aria-label')?.startsWith('Edit'),
    ) as HTMLElement;
    await click(edit);
    await flush(20);
    await click(button('Cancel') as HTMLElement);
    await flush(30);
    expect(document.activeElement).toBe(edit); // that row's Edit, not the dialog container
    await view.unmount();
  });

  it('returns focus to Add after saving a new subscription', async () => {
    let made = false;
    const { view } = await open({
      [`GET ${LIST}`]: () => (made ? [sub()] : []),
      [`POST ${LIST}`]: () => {
        made = true;
        return Response.json(sub(), { status: 201 });
      },
    });
    await click(button('Add a subscription') as HTMLElement);
    await setValue(
      document.getElementById('events-sub-url') as HTMLInputElement,
      'https://a.example/x.ics',
    );
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'Holidays');
    await click(button('Save') as HTMLElement);
    await flush(80);
    expect(document.querySelector('[data-testid="subscription-form"]')).toBeNull();
    expect(document.activeElement).toBe(button('Add a subscription'));
    await view.unmount();
  });

  it('puts focus in the address field, closes the form on the first Escape and the dialog on the next, and returns focus to the trigger', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [] });
    const trigger = document.querySelector('[data-testid="events-subscriptions"]') as HTMLElement;
    await click(button('Add a subscription') as HTMLElement);
    await flush(20);
    expect(document.activeElement?.id).toBe('events-sub-url');
    await press(dialog(), { key: 'Escape' });
    await flush(20);
    expect(document.querySelector('[data-testid="subscription-form"]')).toBeNull();
    expect(dialog()).not.toBeNull(); // the dialog is still open
    await press(dialog(), { key: 'Escape' });
    await flush(50);
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(trigger);
    await view.unmount();
  });
});
