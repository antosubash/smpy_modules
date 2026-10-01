import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../../test-dom';
import type { FieldDef } from '../../utils/types';
import { MultiSelectField } from './ChoiceFields';

function field(values: string[]): FieldDef {
  return {
    key: 'tags',
    type: 'multiselect',
    label: 'Tags',
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: { choices: values.map((value) => ({ value, label: value })) },
  };
}

describe('MultiSelectField — polish: checkbox ids are valid selectors', () => {
  it('does not put a choice value with a space or a # into the id', () => {
    const out = renderToStaticMarkup(
      <MultiSelectField
        field={field(['plain', 'two words', 'has#hash'])}
        value={[]}
        onChange={() => {}}
      />,
    );
    expect(out).toContain('id="record-field-tags-0"');
    expect(out).toContain('id="record-field-tags-1"');
    expect(out).toContain('id="record-field-tags-2"');
    expect(out).not.toContain('id="record-field-tags-two words"');
    expect(out).not.toContain('id="record-field-tags-has#hash"');
    // The label still points at its own box.
    expect(out).toContain('for="record-field-tags-1"');
  });
});
