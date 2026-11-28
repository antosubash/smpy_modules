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

async function waitFor(
  find: (selector: string) => Element | null,
  selector: string,
  act: (fn: () => Promise<void>) => Promise<void>,
) {
  const deadline = Date.now() + 10_000;
  while (!find(selector) && Date.now() < deadline) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
}

describe('records PageLocale (#488)', () => {
  afterEach(async () => {
    vi.doUnmock('../../locales/de.json');
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
    await waitFor(view.find, '[data-testid="probe"]', act);
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

  it('preserves child state without remounting on a same-locale rerender after a cold load', async () => {
    vi.resetModules();
    document.documentElement.lang = '';
    const { keys, useT } = await import('./i18n');
    const { PageLocale } = await import('./PageLocale');
    const { act, click, mount } = await import('../page-tests/test-dom');

    let mounts = 0;
    const onMount = () => {
      mounts += 1;
    };
    const renderTree = () => (
      <PageLocale locale="de">
        <StatefulChild
          useTranslate={useT}
          labelKey={keys.records.public_submissions.form.honeypot}
          onMount={onMount}
        />
      </PageLocale>
    );

    const view = await mount(renderTree());
    await waitFor(view.find, '[data-testid="label"]', act);
    expect(view.find('[data-testid="label"]')?.textContent).toBe('Dieses Feld leer lassen');
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
    const { act, mount } = await import('../page-tests/test-dom');

    const view = await mount(
      <div>
        <span data-testid="sibling">alive</span>
        <PageLocale locale="de">
          <Probe useTranslate={useT} labelKey={keys.records.public_submissions.form.honeypot} />
        </PageLocale>
      </div>,
    );
    await waitFor(view.find, '[data-testid="probe"]', act);
    expect(view.find('[data-testid="sibling"]')?.textContent).toBe('alive');
    expect(view.find('[data-testid="probe"]')?.textContent).toBe('Leave this field empty');
    expect(errors).toEqual([]);
    await view.unmount();
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
