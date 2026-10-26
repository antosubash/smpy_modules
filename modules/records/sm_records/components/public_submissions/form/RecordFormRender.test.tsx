// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mount, settle, setValue } from '../../../test-dom';
import { definition, field, input, send, server } from './record-form-test-support';

vi.mock('@simple-module-py/pagebuilder/pagebuilder/components/widgets/_shared', () => ({
  Section: ({ children }: { children: unknown }) => <section>{children as never}</section>,
}));

// The provider's script cannot load here; the widget's own loader is not
// what these tests are about.
vi.mock('./CaptchaWidget', () => ({
  CaptchaWidget: () => <div data-testid="records-form-captcha" />,
}));

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

describe('RecordFormRender', () => {
  it('renders the live definition: one labelled input per field, the server consent, a hidden trap', async () => {
    const calls = server({ status: 200, body: definition() });
    const view = await mount(block());
    await settle();
    expect(calls[0].url).toBe('/api/records/submissions/contact?locale=de');
    for (const key of ['name', 'email', 'age', 'message', 'topic', 'news']) {
      const el = input(view, key);
      expect(el, key).not.toBeNull();
      const label = view.find(`label[for="${el?.id}"]`);
      expect(label?.textContent).toContain(`${key} label`);
    }
    expect(input(view, 'email')?.getAttribute('type')).toBe('email');
    expect(input(view, 'name')?.getAttribute('aria-required')).toBe('true');
    expect(view.find('[data-testid="records-form-consent"]')?.textContent).toContain(
      'I agree to be contacted.',
    );
    const trap = view.find<HTMLInputElement>('input[name="website"]');
    expect(trap?.tabIndex).toBe(-1);
    expect(trap?.closest('[aria-hidden="true"]')).not.toBeNull();
    await view.unmount();
  });

  it('checks required fields and consent before sending, and says so per field', async () => {
    const calls = server({ status: 200, body: definition() });
    const view = await mount(block());
    await settle();
    await send(view);
    expect(calls).toHaveLength(1);
    expect(view.find('[role="alert"]')?.textContent).toContain(
      'Please check the highlighted fields.',
    );
    expect(input(view, 'name')?.getAttribute('aria-invalid')).toBe('true');
    const describedBy = input(view, 'name')?.getAttribute('aria-describedby') ?? '';
    expect(document.getElementById(describedBy)?.textContent).toBe('Please fill in this field.');
    expect(view.host.textContent).toContain('Please tick this box to continue.');
    await view.unmount();
  });

  it('a form not accepting submissions is unavailable; no type is a placeholder', async () => {
    server({ status: 404, body: { detail: 'not found' } });
    const view = await mount(block());
    await settle();
    expect(view.find('[data-testid="records-form-unavailable"]')?.textContent).toContain(
      "isn't available",
    );
    await view.render(block({ typeKey: '' }));
    expect(view.find('[data-testid="records-form-placeholder"]')).not.toBeNull();
    await view.unmount();
  });

  it('in the editor it shows the live form with its submit disabled', async () => {
    const calls = server({ status: 200, body: definition() });
    const view = await mount(block({ puck: { isEditing: true } }));
    await settle();
    const button = view.find<HTMLButtonElement>('button[type="submit"]');
    expect(button?.disabled).toBe(true);
    expect(view.host.textContent).toContain('Submits on the published page.');
    expect(calls).toHaveLength(1);
    await view.unmount();
  });

  it('a page label override replaces the type label; a newsletter says subscribe', async () => {
    server({
      status: 200,
      body: definition({
        kind: 'subscription',
        consent: null,
        fields: [field('sm_email', 'email', { required: true })],
      }),
    });
    const view = await mount(
      block({ labels: [{ field: 'sm_email', label: 'Ihre E-Mail', help: 'Nur dafür.' }] }),
    );
    await settle();
    expect(view.find('[data-testid="records-form-field-sm_email"]')?.textContent).toContain(
      'Ihre E-Mail',
    );
    expect(view.host.textContent).toContain('Nur dafür.');
    expect(view.find('button[type="submit"]')?.textContent).toBe('Subscribe');
    await view.unmount();
  });

  it('a CAPTCHA named by the definition is rendered, and its response sent', async () => {
    const calls = server(
      {
        status: 200,
        body: definition({ captcha: { provider: 'turnstile', site_key: 'k' }, consent: null }),
      },
      { status: 400, body: { code: 'captcha_failed' } },
    );
    const view = await mount(block());
    await settle();
    expect(view.find('[data-testid="records-form-captcha"]')).not.toBeNull();
    await setValue(input(view, 'name') as HTMLInputElement, 'Ada');
    await setValue(input(view, 'email') as HTMLInputElement, 'ada@example.org');
    await send(view);
    expect(JSON.parse(String(calls[1].init?.body))).toHaveProperty('captcha_response', '');
    expect(view.find('[role="alert"]')?.textContent).toContain('security check');
    await view.unmount();
  });

  it('a form loaded before the CAPTCHA was turned on fetches the one that names it', async () => {
    server(
      { status: 200, body: definition({ consent: null }) },
      { status: 400, body: { code: 'captcha_failed' } },
      {
        status: 200,
        body: definition({ captcha: { provider: 'hcaptcha', site_key: 'k' }, consent: null }),
      },
    );
    const view = await mount(block());
    await settle();
    expect(view.find('[data-testid="records-form-captcha"]')).toBeNull();
    await setValue(input(view, 'name') as HTMLInputElement, 'Ada');
    await setValue(input(view, 'email') as HTMLInputElement, 'ada@example.org');
    await send(view);
    await settle();
    expect(view.find('[data-testid="records-form-captcha"]')).not.toBeNull();
    expect((input(view, 'name') as HTMLInputElement).value).toBe('Ada');
    await view.unmount();
  });
});
