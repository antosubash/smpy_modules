import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../../test-dom';
import { FieldRowBody } from './FieldRowBody';
import type { EditableField } from './types';

function field(overrides: Partial<EditableField> = {}): EditableField {
  return {
    key: 'title',
    uid: 'u1',
    fromServer: true,
    type: 'text',
    label: 'Title',
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

function html(overrides: Partial<EditableField> = {}): string {
  return renderToStaticMarkup(
    <FieldRowBody
      field={field(overrides)}
      index={0}
      keyLocked={false}
      siblingKeys={[]}
      targetTypes={[]}
      disabled={false}
      errors={[]}
      onChange={() => {}}
      onPatch={() => {}}
    />,
  );
}

describe('FieldRowBody — R11: the Type select says words, not wire values', () => {
  it("names every field type in the operator's language", () => {
    const out = html();
    expect(out).toContain('Long text');
    expect(out).toContain('Yes / no');
    expect(out).toContain('Date and time');
    expect(out).toContain('Several choices');
    expect(out).toContain('Link to a record');
    // The wire value stays on the option, which is what the form submits.
    expect(out).toContain('value="longtext"');
    expect(out).toContain('value="relation"');
  });

  it('carries the API length caps as maxLength (R3)', () => {
    const out = html();
    expect(out).toMatch(/id="field-row-0-key"[^>]*maxLength="64"/);
    expect(out).toMatch(/id="field-row-0-label"[^>]*maxLength="200"/);
  });
});
