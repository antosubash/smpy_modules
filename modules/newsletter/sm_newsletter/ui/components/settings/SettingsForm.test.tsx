// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import en from '../../../locales/en.json';
import { api } from '../../utils/api';
import type { SettingsOut } from '../../utils/types';
import { SettingsForm } from './SettingsForm';

vi.mock('../../utils/api', () => ({
  api: { putSettings: vi.fn(), putPassword: vi.fn() },
  errorMessage: () => 'failed',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.settings;

const INITIAL: SettingsOut = {
  transport: 'smtp',
  smtp_host: 'smtp.example.com',
  smtp_port: 587,
  smtp_security: 'starttls',
  smtp_username: 'mailer',
  has_password: true,
  from_address: 'news@example.com',
  from_name: 'News',
  reply_to: '',
  daily_limit: 1000,
  per_minute_limit: 60,
  tracking_opens: false,
  tracking_clicks: false,
  physical_address: '1 Main St',
  test_send_extra_recipients: [],
};

function typeInto(el: HTMLInputElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  set?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('SettingsForm', () => {
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    vi.mocked(api.putSettings).mockReset();
    vi.mocked(api.putPassword).mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(props: { initial?: Partial<SettingsOut>; canWrite: boolean }) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(SettingsForm, {
          initial: { ...INITIAL, ...props.initial },
          canWrite: props.canWrite,
        }),
      ),
    );
  }

  const field = (label: string) =>
    [...document.querySelectorAll('input')].find(
      (i) => document.querySelector(`label[for="${i.id}"]`)?.textContent === label,
    ) as HTMLInputElement;
  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label);

  it('warns before a server change', async () => {
    await render({ canWrite: true });
    expect(document.body.textContent).not.toContain(copy.server_change_clears_password);
    await act(async () => typeInto(field(copy.transport.host), 'smtp.other.example'));
    expect(document.body.textContent).toContain(copy.server_change_clears_password);
    await act(async () => typeInto(field(copy.transport.host), 'smtp.example.com'));
    expect(document.body.textContent).not.toContain(copy.server_change_clears_password);
  });

  it('does not warn when no password is stored', async () => {
    await render({ canWrite: true, initial: { has_password: false } });
    await act(async () => typeInto(field(copy.transport.host), 'smtp.other.example'));
    expect(document.body.textContent).not.toContain(copy.server_change_clears_password);
  });

  it('never renders the password value', async () => {
    await render({ canWrite: true });
    const password = field(copy.password.label);
    expect(password.type).toBe('password');
    expect(password.value).toBe('');
    expect(document.body.textContent).toContain(copy.password.saved);
    vi.mocked(api.putPassword).mockResolvedValue({ has_password: true });
    await act(async () => typeInto(password, 'hunter2-secret'));
    await act(async () => button(copy.password.save)?.click());
    expect(api.putPassword).toHaveBeenCalledWith('hunter2-secret');
    expect(password.value).toBe('');
    expect(document.body.innerHTML).not.toContain('hunter2-secret');
  });

  it('shows the notice after a save that cleared the password', async () => {
    await render({ canWrite: true });
    await act(async () => typeInto(field(copy.transport.host), 'smtp.other.example'));
    vi.mocked(api.putSettings).mockResolvedValue({
      ...INITIAL,
      smtp_host: 'smtp.other.example',
      has_password: false,
      password_cleared: true,
    });
    await act(async () => button(copy.save)?.click());
    expect(document.body.textContent).toContain(copy.password_cleared_notice);
    expect(document.body.textContent).toContain(copy.password.not_saved);
  });

  it('read-only without can_write', async () => {
    await render({ canWrite: false });
    expect(document.body.textContent).toContain(copy.read_only_note);
    for (const input of document.querySelectorAll('input, select, textarea')) {
      expect((input as HTMLInputElement).disabled).toBe(true);
    }
    expect(button(copy.save)).toBeUndefined();
    expect(button(copy.password.save)).toBeUndefined();
  });

  it('saves the extra test recipients as a normalised list (#348)', async () => {
    await render({ canWrite: true });
    const area = document.getElementById(
      'newsletter-settings-test-recipients',
    ) as HTMLTextAreaElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      set?.call(area, ' Review@Example.org\nqa@example.org, review@example.org\n');
      area.dispatchEvent(new Event('input', { bubbles: true }));
    });
    vi.mocked(api.putSettings).mockResolvedValue({ ...INITIAL, password_cleared: false });
    await act(async () => button(copy.save)?.click());
    expect(vi.mocked(api.putSettings).mock.calls[0][0]).toMatchObject({
      test_send_extra_recipients: ['review@example.org', 'qa@example.org'],
    });
  });

  it('keeps Save disabled while the extra recipients are over the limit', async () => {
    await render({ canWrite: true });
    const area = document.getElementById(
      'newsletter-settings-test-recipients',
    ) as HTMLTextAreaElement;
    const fill = async (text: string) =>
      act(async () => {
        const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
        set?.call(area, text);
        area.dispatchEvent(new Event('input', { bubbles: true }));
      });
    await fill(Array.from({ length: 21 }, (_, i) => `r${i}@example.org`).join('\n'));
    expect((button(copy.save) as HTMLButtonElement).disabled).toBe(true);
    await fill('r1@example.org');
    expect((button(copy.save) as HTMLButtonElement).disabled).toBe(false);
  });
});
