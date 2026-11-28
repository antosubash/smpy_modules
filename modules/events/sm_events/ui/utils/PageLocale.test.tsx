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

describe('PageLocale (#489)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
    document.documentElement.lang = '';
  });

  it('loads a cold German catalogue without a React use() error, and renders later mounts synchronously', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    const errors: unknown[][] = [];
    vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args);
    });

    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { mount, ready } = await import('../page-tests/test-dom');

    const first = await mount(
      <PageLocale locale="de">
        <Probe useTranslate={useT} labelKey={keys.events.public.event.register} />
      </PageLocale>,
    );
    await ready(first, '[data-testid="probe"]');
    expect(first.find('[data-testid="probe"]')?.textContent).toBe('Anmelden');
    expect(first.find('[data-testid="probe"]')?.getAttribute('data-locale')).toBe('de');
    expect(errors.map((a) => a.join(' ')).join('\n')).not.toContain('use()');
    expect(errors).toEqual([]);
    await first.unmount();

    // Once cached, a fresh mount renders synchronously without suspending.
    const second = await mount(
      <PageLocale locale="de">
        <Probe useTranslate={useT} labelKey={keys.events.public.event.register} />
      </PageLocale>,
    );
    expect(second.find('[data-testid="probe"]')?.textContent).toBe('Anmelden');
    await second.unmount();
  });

  it('maps regional tags to their base catalogue and renders English without waiting', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    const { keys, useT } = await import('./i18n');
    const { PageLocale, loadCatalogue } = await import('./PageLocale');
    await loadCatalogue('de');
    const { mount } = await import('../page-tests/test-dom');

    const deAt = await mount(
      <PageLocale locale="de-AT">
        <Probe useTranslate={useT} labelKey={keys.events.public.event.register} />
      </PageLocale>,
    );
    expect(deAt.find('[data-testid="probe"]')?.textContent).toBe('Anmelden');
    expect(deAt.find('[data-testid="probe"]')?.getAttribute('data-locale')).toBe('de-AT');
    await deAt.unmount();

    const en = await mount(
      <PageLocale locale="en">
        <Probe useTranslate={useT} labelKey={keys.events.public.event.register} />
      </PageLocale>,
    );
    expect(en.find('[data-testid="probe"]')?.textContent).toBe('Register');
    await en.unmount();
  });
});
