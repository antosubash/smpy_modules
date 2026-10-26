// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount, settle, setValue } from '../../../test-dom';
import { definition, field, fill, input, send, server } from './record-form-test-support';

vi.mock('@simple-module-py/pagebuilder/pagebuilder/components/widgets/_shared', () => ({
  Section: ({ children }: { children: unknown }) => <section>{children as never}</section>,
}));

// The provider's script cannot load here: a stand-in widget hands over a
// response at once (unless a test sets `widget.token` to '').
const widget = vi.hoisted(() => ({ token: 'cap-token' }));
vi.mock('./CaptchaWidget', async () => {
  const { useEffect } = await import('react');
  return {
    CaptchaWidget: ({ round, onToken }: { round: number; onToken: (t: string) => void }) => {
      useEffect(() => {
        if (widget.token) onToken(widget.token);
      }, [round, onToken]);
      return <div data-testid="records-form-captcha" data-round={round} />;
    },
  };
});

const { RecordFormRender } = await import('./RecordFormRender');

function block(extra: Record<string, unknown> = {}) {
  return (
    <RecordFormRender
      id="RecordForm-abc"
      typeKey="contact"
      title="Write to us"
      intro=""
      submitLabel=""
      successTitle=""
      successBody=""
      labels={[]}
      kindHint=""
      {...extra}
    />
  );
}

beforeEach(() => {
  document.documentElement.lang = 'de';
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.lang = '';
});

describe('RecordFormRender — sending', () => {
  it('sends the values with the token and shows the thank-you', async () => {
    const calls = server({ status: 200, body: definition() }, { status: 202, body: { ok: true } });
    const view = await mount(block());
    await settle();
    await fill(view);
    await send(view);
    const body = JSON.parse(String(calls[1].init?.body));
    expect(calls[1].url).toBe('/api/records/submissions/contact/submit');
    expect(calls[1].init?.headers).toMatchObject({ 'Content-Type': 'application/json' });
    expect(body).toEqual({
      data: { name: 'Ada', email: 'ada@example.org', age: 36, news: false },
      token: 'tok-1',
      hp: '',
      consent: true,
      block: 'RecordForm-abc',
      locale: 'de',
    });
    const success = view.find('[data-testid="records-form-success"]');
    expect(success?.getAttribute('role')).toBe('status');
    expect(success?.textContent).toContain('Thank you');
    await view.unmount();
  });

  it('a stale token fetches a fresh form and sends once more, once it is old enough', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    const fresh = definition({ token: 'tok-2', min_fill_seconds: 3 });
    const calls = server(
      { status: 200, body: definition() },
      { status: 400, body: { detail: 'x', code: 'form_expired' } },
      { status: 200, body: fresh },
      { status: 202, body: { ok: true } },
      { status: 202, body: { ok: true } },
    );
    const view = await mount(block());
    await settle();
    await fill(view);
    await send(view);
    await settle();
    // Sent at once, the fresh token would be refused as too young again.
    expect(calls.map((c) => c.init?.method ?? 'GET')).toEqual(['GET', 'POST', 'GET']);
    expect(view.find<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_900);
    });
    expect(calls).toHaveLength(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await settle();
    vi.useRealTimers();
    expect(calls.map((c) => c.init?.method ?? 'GET')).toEqual(['GET', 'POST', 'GET', 'POST']);
    expect(JSON.parse(String(calls[3].init?.body)).token).toBe('tok-2');
    expect(view.find('[data-testid="records-form-success"]')).not.toBeNull();
    await view.unmount();
  });

  it('form_changed re-renders the new form and keeps what was typed', async () => {
    const changed = definition({
      token: 'tok-3',
      fields: [field('name', 'text', { required: true }), field('phone', 'text')],
    });
    server(
      { status: 200, body: definition() },
      { status: 409, body: { detail: 'x', code: 'form_changed', definition: changed } },
    );
    const view = await mount(block());
    await settle();
    await fill(view);
    await send(view);
    expect(input(view, 'phone')).not.toBeNull();
    expect(input(view, 'email')).toBeNull();
    expect((input(view, 'name') as HTMLInputElement).value).toBe('Ada');
    expect(view.find('[role="alert"]')?.textContent).toContain('This form changed');
    await view.unmount();
  });

  it('maps a 422 onto its fields, and says how long to wait after a 429', async () => {
    server(
      { status: 200, body: definition() },
      {
        status: 422,
        body: { code: 'invalid', errors: [{ field: 'email', message: 'not an email' }] },
      },
      { status: 429, body: { code: 'rate_limited' }, headers: { 'Retry-After': '42' } },
    );
    const view = await mount(block());
    await settle();
    await fill(view);
    await send(view);
    expect(input(view, 'email')?.getAttribute('aria-invalid')).toBe('true');
    expect(view.host.textContent).toContain('Please check this value.');
    await send(view);
    expect(view.find('[role="alert"]')?.textContent).toContain('wait 42 seconds');
    await view.unmount();
  });

  it('after a refusal past the CAPTCHA check, the widget starts over', async () => {
    const calls = server(
      {
        status: 200,
        body: definition({ captcha: { provider: 'turnstile', site_key: 'k' }, consent: null }),
      },
      { status: 422, body: { code: 'invalid', errors: [{ field: 'email', message: 'x' }] } },
    );
    const view = await mount(block());
    await settle();
    const before = view.find('[data-testid="records-form-captcha"]')?.getAttribute('data-round');
    await setValue(input(view, 'name') as HTMLInputElement, 'Ada');
    await setValue(input(view, 'email') as HTMLInputElement, 'ada@example.org');
    await send(view);
    expect(calls).toHaveLength(2);
    const after = view.find('[data-testid="records-form-captcha"]')?.getAttribute('data-round');
    expect(Number(after)).toBeGreaterThan(Number(before));
    await view.unmount();
  });
});
