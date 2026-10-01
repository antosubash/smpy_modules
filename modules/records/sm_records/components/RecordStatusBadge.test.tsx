import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../test-dom';
import type { RecordRead } from '../utils/record-types';
import { RecordEditorHeaderBadges, SchemaStaleBadge } from './RecordStatusBadge';

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return {
    uuid: 'r1',
    schema_stale: false,
    is_deleted: false,
    locale: 'en',
    ...overrides,
  } as unknown as RecordRead;
}

describe('the schema-stale badge — U13(c): one label, not two', () => {
  it('the list badge and the editor header badge say the same thing', () => {
    const listBadge = renderToStaticMarkup(<SchemaStaleBadge />);
    const headerBadges = renderToStaticMarkup(
      <RecordEditorHeaderBadges current={record({ schema_stale: true })} translatable={false} />,
    );
    expect(listBadge).toContain('Outdated schema');
    expect(headerBadges).toContain('Outdated schema');
    // The wording this replaced must be gone from both surfaces.
    expect(headerBadges).not.toContain('Fields changed since this was saved');
  });
});
