// @vitest-environment happy-dom
import { useEffect, useState } from 'react';
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

function StatefulChild({
  useTranslate,
  labelKey,
  onMount,
}: {
  useTranslate: () => { t: (k: string) => string };
  labelKey: string;
  onMount: () => void;
}) {
  const { t } = useTranslate();
  const [value, setValue] = useState('initial');
  useEffect(() => {
    onMount();
  }, [onMount]);
  return (
    <div>
      <span data-testid="label">{t(labelKey)}</span>
      <span data-testid="state">{value}</span>
      <button type="button" data-testid="mutate" onClick={() => setValue('edited')}>
        edit
      </button>
    </div>
  );
}

describe('PageLocale (#489)', () => {
  afterEach(() => {
    vi.doUnmock('../../locales/de.json');
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

  it('preserves child state without remounting on a same-locale rerender after a cold load', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { click, mount, ready } = await import('../page-tests/test-dom');

    let mounts = 0;
    const onMount = () => {
      mounts += 1;
    };
    const renderTree = () => (
      <PageLocale locale="de">
        <StatefulChild
          useTranslate={useT}
          labelKey={keys.events.public.event.register}
          onMount={onMount}
        />
      </PageLocale>
    );

    const view = await mount(renderTree());
    await ready(view, '[data-testid="label"]');
    expect(view.find('[data-testid="label"]')?.textContent).toBe('Anmelden');
    await click(view.find('[data-testid="mutate"]'));
    expect(view.find('[data-testid="state"]')?.textContent).toBe('edited');
    expect(mounts).toBe(1);

    await view.render(renderTree());
    expect(view.find('[data-testid="state"]')?.textContent).toBe('edited');
    expect(mounts).toBe(1);
    await view.unmount();
  });

  it('falls back to English without blanking siblings when the German chunk fails to load', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    vi.doMock('../../locales/de.json', () => {
      throw new Error('chunk failed');
    });
    const errors: unknown[][] = [];
    vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args);
    });

    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { mount, ready } = await import('../page-tests/test-dom');

    const view = await mount(
      <div>
        <span data-testid="sibling">alive</span>
        <PageLocale locale="de">
          <Probe useTranslate={useT} labelKey={keys.events.public.event.register} />
        </PageLocale>
      </div>,
    );
    await ready(view, '[data-testid="probe"]');
    expect(view.find('[data-testid="sibling"]')?.textContent).toBe('alive');
    expect(view.find('[data-testid="probe"]')?.textContent).toBe('Register');
    expect(errors).toEqual([]);
    await view.unmount();
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
