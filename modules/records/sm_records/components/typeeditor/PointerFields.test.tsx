import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../../test-dom';
import { PointerFields } from './PointerFields';
import type { EditableField, TypeMetadataValues } from './types';

function field(key: string, extra: Partial<EditableField> = {}): EditableField {
  return {
    key,
    type: 'text',
    label: key,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    uid: key,
    fromServer: true,
    ...extra,
  };
}

describe('PointerFields — internal system fields (#101)', () => {
  it('never offers sm_nonce as the display or slug field', () => {
    const html = renderToStaticMarkup(
      <PointerFields
        fields={[
          field('sm_email', { type: 'email', system: 'readonly' }),
          field('sm_nonce', { system: 'internal' }),
        ]}
        values={{ displayField: 'sm_email', slugField: '' } as TypeMetadataValues}
        errors={[]}
        onChange={() => {}}
      />,
    );
    expect(html).toContain('value="sm_email"');
    expect(html).not.toContain('sm_nonce');
  });
});
