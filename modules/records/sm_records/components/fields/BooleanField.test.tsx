// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { mount, setValue } from '../../test-dom';
import type { FieldDef } from '../../utils/types';
import { BooleanField } from './BooleanField';

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'flag',
    type: 'boolean',
    label: 'Flag',
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

describe('BooleanField — R7: a never-set boolean says so', () => {
  it('renders a required unset boolean as a three-option select, not an off switch', async () => {
    const view = await mount(
      <BooleanField
        field={field({ required: true })}
        value={null}
        onChange={() => {}}
        error="This field is required"
      />,
    );
    const select = view.find<HTMLSelectElement>('#record-field-flag');
    expect(select?.tagName).toBe('SELECT');
    expect([...(select?.options ?? [])].map((o) => o.value)).toEqual(['', 'true', 'false']);
    expect(select?.value).toBe('');
    // Before R7 this was a `<Switch>` rendered `checked={value === true}` —
    // indistinguishable from a deliberate "No" — under the very message
    // telling the person to set it.
    expect(view.find('button[role="switch"]')).toBeNull();
    view.unmount();
  });

  it('reports a real boolean, and drops the unset option once one is chosen', async () => {
    let value: unknown = null;
    const view = await mount(
      <BooleanField
        field={field({ required: true })}
        value={value}
        onChange={(next) => {
          value = next;
        }}
      />,
    );
    await setValue(
      view.find<HTMLSelectElement>('#record-field-flag') as HTMLSelectElement,
      'false',
    );
    expect(value).toBe(false);

    await view.render(
      <BooleanField field={field({ required: true })} value={false} onChange={() => {}} />,
    );
    const select = view.find<HTMLSelectElement>('#record-field-flag');
    expect([...(select?.options ?? [])].map((o) => o.value)).toEqual(['true', 'false']);
    expect(select?.value).toBe('false');
    view.unmount();
  });

  it('keeps the switch for an optional boolean, labelled "Not set" while it is', async () => {
    const view = await mount(<BooleanField field={field()} value={null} onChange={() => {}} />);
    expect(view.find('button[role="switch"]')).not.toBeNull();
    expect(view.find('[data-testid="records-unset-flag"]')?.textContent).toBe('Not set');

    await view.render(<BooleanField field={field()} value={false} onChange={() => {}} />);
    expect(view.find('[data-testid="records-unset-flag"]')).toBeNull();
    view.unmount();
  });
});
