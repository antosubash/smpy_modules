// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { mount } from '../../test-dom';
import type { FieldDef } from '../../utils/types';
import { MediaField } from './TextFields';

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'image',
    type: 'media',
    label: 'Image',
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

describe('MediaField — U18: a bare text box explains what it wants', () => {
  it('shows a built-in hint and placeholder when the schema author set no help', async () => {
    const view = await mount(<MediaField field={field()} value="" onChange={() => {}} />);
    expect(view.host.textContent).toContain('media library id');
    const input = view.find<HTMLInputElement>('#record-field-image');
    expect(input?.placeholder).toContain('media id or');
    await view.unmount();
  });

  it("lets the schema author's own help win over the fallback", async () => {
    const view = await mount(
      <MediaField
        field={field({ help: 'Paste the product photo id from the DAM.' })}
        value=""
        onChange={() => {}}
      />,
    );
    expect(view.host.textContent).toContain('Paste the product photo id from the DAM.');
    expect(view.host.textContent).not.toContain('media library id');
    await view.unmount();
  });
});
