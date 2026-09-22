// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest';

import { rememberDuplicate, takeDuplicate } from './duplicate';
import type { FieldDef, RecordRead } from './types';

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'title',
    type: 'text',
    label: 'Title',
    required: false,
    unique: false,
    indexed: true,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return {
    uuid: 'u1',
    type_key: 'book',
    status: 'draft',
    slug: 'dune',
    locale: 'en',
    translation_group: null,
    display_title: 'Dune',
    position: 3,
    version: 5,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: false,
    data: { title: 'Dune', isbn: '000-1', notes: 'first edition' },
    invalid: [],
    ...overrides,
  } as unknown as RecordRead;
}

beforeEach(() => {
  window.sessionStorage.clear();
});

describe('duplicate — Missing-item "Save as copy": prefilled minus uuid/slug/unique', () => {
  it('carries every field forward except one marked unique', () => {
    const fields = [field({ key: 'title' }), field({ key: 'isbn', unique: true })];
    rememberDuplicate('book', fields, record());
    const taken = takeDuplicate('book');
    expect(taken?.data).toEqual({ title: 'Dune', notes: 'first edition' });
    expect(taken?.data).not.toHaveProperty('isbn');
  });

  it('never carries a uuid or slug at all — they are not part of the payload shape', () => {
    const fields = [field()];
    rememberDuplicate('book', fields, record());
    const taken = takeDuplicate('book');
    expect(taken).not.toHaveProperty('uuid');
    expect(taken).not.toHaveProperty('slug');
  });

  it('carries status and position forward, unmarked fields untouched', () => {
    const fields = [field()];
    rememberDuplicate('book', fields, record({ status: 'published', position: 7 }));
    const taken = takeDuplicate('book');
    expect(taken?.status).toBe('published');
    expect(taken?.position).toBe(7);
  });

  it('is read-once: a second take for the same type sees nothing', () => {
    rememberDuplicate('book', [field()], record());
    expect(takeDuplicate('book')).not.toBeNull();
    expect(takeDuplicate('book')).toBeNull();
  });

  it('is scoped per type key — a duplicate stashed for one type is invisible to another', () => {
    rememberDuplicate('book', [field()], record());
    expect(takeDuplicate('article')).toBeNull();
    // …and is still there for the type it was actually stashed for.
    expect(takeDuplicate('book')).not.toBeNull();
  });

  it('returns null when nothing was stashed', () => {
    expect(takeDuplicate('book')).toBeNull();
  });
});
