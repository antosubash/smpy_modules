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

describe('FieldRowBody — U6: the Indexed checkbox names its own consequence', () => {
  it('renders a hint naming the list-column consequence, wired to the checkbox', () => {
    const out = html();
    expect(out).toContain('id="field-row-0-indexed-hint"');
    expect(out).toContain('aria-describedby="field-row-0-indexed-hint"');
    expect(out).toContain('Indexed fields can be filtered and sorted');
    expect(out).toContain('Columns menu');
    expect(out).toContain('first four indexed fields');
  });
});

describe('FieldRowBody — U19: "Unique" says what it does not cover', () => {
  it('renders the translation-group exemption, wired to the checkbox, for a field that allows unique', () => {
    const out = html();
    expect(out).toContain('id="field-row-0-unique-hint"');
    expect(out).toContain('aria-describedby="field-row-0-unique-hint"');
    expect(out).toContain('translations of the same record');
  });

  it('says nothing for a field type that cannot be unique at all', () => {
    const out = html({ type: 'longtext' });
    expect(out).not.toContain('field-row-0-unique-hint');
  });
});
