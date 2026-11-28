// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

function Probe({
  useTranslate,
  labelKey,
}: {
  useTranslate: () => { t: (k: string) => string; locale: string | undefined };
  labelKey: string;
}) {
  const { t, locale } = useTranslate();
  return (
    <span data-testid="probe" data-locale={locale}>
      {t(labelKey)}
    </span>
  );
}

describe('records PageLocale (#488)', () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
    document.documentElement.lang = '';
    const { updateI18n } = await import('@simple-module-py/i18n');
    updateI18n({ locale: 'en', messages: {} });
  });

  it('loads a cold German catalogue without a React use() error and ignores console language', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    const { updateI18n } = await import('@simple-module-py/i18n');
    updateI18n({ locale: 'en', messages: {} });
    const errors: unknown[][] = [];
    vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args);
    });

    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { mount, act } = await import('../page-tests/test-dom');

    const view = await mount(
      <PageLocale locale="de">
        <Probe useTranslate={useT} labelKey={keys.records.public_submissions.form.honeypot} />
      </PageLocale>,
    );
    const deadline = Date.now() + 10_000;
    while (!view.find('[data-testid="probe"]') && Date.now() < deadline) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 20));
      });
    }
    expect(view.find('[data-testid="probe"]')?.textContent).toBe('Dieses Feld leer lassen');
    expect(view.find('[data-testid="probe"]')?.getAttribute('data-locale')).toBe('de');
    expect(errors).toEqual([]);
    await view.unmount();

    const second = await mount(
      <PageLocale locale="de">
        <Probe useTranslate={useT} labelKey={keys.records.public_submissions.form.honeypot} />
      </PageLocale>,
    );
    expect(second.find('[data-testid="probe"]')?.textContent).toBe('Dieses Feld leer lassen');
    await second.unmount();
  });

  it('renders English inside <PageLocale locale="en"> even when the console speaks German', async () => {
    vi.resetModules();
    const { updateI18n } = await import('@simple-module-py/i18n');
    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { mount } = await import('../page-tests/test-dom');
    updateI18n({
      locale: 'de',
      messages: { 'records.public_submissions.form.honeypot': 'Dieses Feld leer lassen' },
    });

    const view = await mount(
      <PageLocale locale="en">
        <Probe useTranslate={useT} labelKey={keys.records.public_submissions.form.honeypot} />
      </PageLocale>,
    );
    expect(view.find('[data-testid="probe"]')?.textContent).toBe('Leave this field empty');
    expect(view.find('[data-testid="probe"]')?.getAttribute('data-locale')).toBe('en');
    await view.unmount();

    const consoleView = await mount(
      <Probe useTranslate={useT} labelKey={keys.records.public_submissions.form.honeypot} />,
    );
    expect(consoleView.find('[data-testid="probe"]')?.textContent).toBe('Dieses Feld leer lassen');
    expect(consoleView.find('[data-testid="probe"]')?.getAttribute('data-locale')).toBe('de');
    await consoleView.unmount();
  });
});
