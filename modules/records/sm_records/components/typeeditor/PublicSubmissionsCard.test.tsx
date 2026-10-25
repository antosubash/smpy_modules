// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount, setValue } from '../../test-dom';
import { defaultConfig, type PublicSubmissionsConfig } from '../../utils/public-submissions';
import type { EditableField } from './types';

const { PublicSubmissionsCard } = await import('./PublicSubmissionsCard');

function row(key: string, type: string, extra: Partial<EditableField> = {}): EditableField {
  return {
    uid: key,
    fromServer: true,
    key,
    type,
    label: key,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...extra,
  };
}

const FIELDS = [
  row('name', 'text', { required: true }),
  row('photo', 'media'),
  row('sm_spam', 'select', { system: 'readonly' }),
];

function card(over: Partial<Parameters<typeof PublicSubmissionsCard>[0]> = {}) {
  return (
    <PublicSubmissionsCard
      isNew={false}
      savedKind={null}
      config={null}
      fields={FIELDS}
      allowedRoles={[]}
      isPublic={false}
      contentLocales={['en', 'de']}
      errors={[]}
      onChange={vi.fn()}
      onPreset={vi.fn()}
      {...over}
    />
  );
}

const enabledSwitch = (view: Awaited<ReturnType<typeof mount>>) =>
  view.find('#public-submissions-enabled');

describe('PublicSubmissionsCard', () => {
  it('turning it on gives an ordinary type an enabled contact form', async () => {
    const onChange = vi.fn();
    const view = await mount(card({ onChange }));
    expect(view.find('#public-submissions-kind')).toBeNull();
    await click(enabledSwitch(view));
    expect(onChange).toHaveBeenCalledWith({ ...defaultConfig('form'), enabled: true });
    await view.unmount();
  });

  it('turning it off before the kind was saved discards the draft', async () => {
    const onChange = vi.fn();
    const config = { ...defaultConfig('form'), enabled: true };
    const view = await mount(card({ config, onChange }));
    await click(enabledSwitch(view));
    expect(onChange).toHaveBeenCalledWith(null);
    await view.unmount();
  });

  it('turning it off once saved keeps the kind and only disables it', async () => {
    const onChange = vi.fn();
    const config = { ...defaultConfig('form'), enabled: true };
    const view = await mount(card({ config, savedKind: 'form', onChange }));
    await click(enabledSwitch(view));
    expect(onChange).toHaveBeenCalledWith({ ...config, enabled: false });
    expect(view.find<HTMLSelectElement>('#public-submissions-kind')?.disabled).toBe(true);
    await view.unmount();
  });

  it('warns about open roles and missing recipients, and not once roles are set', async () => {
    const config = defaultConfig('form');
    const view = await mount(card({ config }));
    const notes = view.all('[role="note"]').map((el) => el.textContent);
    expect(notes.some((text) => text?.includes('records.view'))).toBe(true);
    expect(notes.some((text) => text?.includes('Nobody is notified'))).toBe(true);
    await view.render(card({ config, allowedRoles: ['support'] }));
    expect(view.all('[role="note"]').some((el) => el.textContent?.includes('records.view'))).toBe(
      false,
    );
    await view.unmount();
  });

  it('lists ordinary fields only, greying the ones a visitor cannot fill', async () => {
    const view = await mount(card({ config: defaultConfig('form') }));
    const boxes = view.all('[data-testid="records-public-fields"] button[role="checkbox"]');
    expect(boxes).toHaveLength(2);
    expect(boxes[1].hasAttribute('disabled')).toBe(true);
    expect(view.host.textContent).toContain("A media field can't be filled in");
    expect(view.host.textContent).not.toContain('sm_spam');
    await view.unmount();
  });

  it('greys out a unique field, which a visitor cannot fill', async () => {
    const fields = [row('ref', 'text', { unique: true })];
    const view = await mount(card({ config: defaultConfig('form'), fields }));
    const box = view.find('[data-testid="records-public-fields"] button[role="checkbox"]');
    expect(box?.hasAttribute('disabled')).toBe(true);
    expect(view.host.textContent).toContain("A unique field can't be filled in");
    await view.unmount();
  });

  it('flags a stored public field that is unique, which the form leaves out', async () => {
    const fields = [row('ref', 'text', { unique: true })];
    const config = { ...defaultConfig('form'), public_fields: ['ref'] };
    const view = await mount(card({ config, fields }));
    const box = view.find('[data-testid="records-public-fields"] button[role="checkbox"]');
    expect(box?.hasAttribute('disabled')).toBe(false);
    expect(view.find('[data-testid="records-public-field-ignored"]')?.textContent).toContain(
      "A unique field can't be filled in",
    );
    await view.unmount();
  });

  it('says which required field blocks an enabled form', async () => {
    const config: PublicSubmissionsConfig = { ...defaultConfig('form'), enabled: true };
    const view = await mount(card({ config }));
    expect(view.host.textContent).toContain('Required with no default');
    await view.unmount();
  });

  it('offers presets only on a new type', async () => {
    const onPreset = vi.fn();
    const view = await mount(card({ isNew: true, onPreset }));
    await click(view.button('Newsletter list'));
    expect(onPreset).toHaveBeenCalledWith('subscription');
    await view.render(card({ isNew: false }));
    expect(view.find('[data-testid="records-public-submissions-presets"]')).toBeNull();
    await view.unmount();
  });

  it('shows the newsletter options and a consent text per content locale', async () => {
    const config: PublicSubmissionsConfig = {
      ...defaultConfig('subscription'),
      consent: { required: true, text: { en: 'Yes' } },
    };
    const view = await mount(card({ config, savedKind: 'subscription' }));
    expect(view.find('#public-submissions-double-opt-in')).not.toBeNull();
    expect(view.find('#public-submissions-notify-to')).toBeNull();
    expect(view.find('#public-submissions-consent-en')).not.toBeNull();
    expect(view.find('#public-submissions-consent-de')).not.toBeNull();
    await view.unmount();
  });

  it('shows the server refusal naming the config', async () => {
    const errors = [{ field: 'public_submissions', message: 'nope, not like that' }];
    const view = await mount(card({ config: defaultConfig('form'), errors }));
    expect(view.find('[role="alert"]')?.textContent).toBe('nope, not like that');
    await view.unmount();
  });

  it('a day count can be cleared and retyped; only a whole number is sent', async () => {
    const onChange = vi.fn();
    const config = defaultConfig('form');
    const view = await mount(card({ config, savedKind: 'form', onChange }));
    const input = view.find<HTMLInputElement>('#public-submissions-retention');
    if (!input) throw new Error('no retention input');
    await setValue(input, '');
    expect(input.value).toBe('');
    expect(onChange).not.toHaveBeenCalled();
    await setValue(input, '30');
    expect(onChange).toHaveBeenLastCalledWith({ ...config, retention_days: 30 });
    onChange.mockClear();
    await setValue(input, '12.7');
    expect(onChange).not.toHaveBeenCalled();
    await view.unmount();
  });
});
