import { describe, expect, it } from 'vitest';

import {
  buildPublicListUrl,
  clampLimit,
  DEFAULT_PUBLIC_PREFIX,
  isValidFilterTerm,
  isValidSortTerm,
  normalizePublicPrefix,
} from './public-api';

describe('normalizePublicPrefix', () => {
  it('defaults a blank prefix', () => {
    expect(normalizePublicPrefix(undefined)).toBe(DEFAULT_PUBLIC_PREFIX);
    expect(normalizePublicPrefix(null)).toBe(DEFAULT_PUBLIC_PREFIX);
    expect(normalizePublicPrefix('   ')).toBe(DEFAULT_PUBLIC_PREFIX);
  });

  it('strips one or more trailing slashes', () => {
    expect(normalizePublicPrefix('/api/records/public/')).toBe('/api/records/public');
    expect(normalizePublicPrefix('/api/records/public///')).toBe('/api/records/public');
  });

  it('leaves an already-normal prefix untouched', () => {
    expect(normalizePublicPrefix('/site/data')).toBe('/site/data');
  });

  it('falls back when trimming leaves nothing (a bare "/")', () => {
    expect(normalizePublicPrefix('/')).toBe(DEFAULT_PUBLIC_PREFIX);
  });
});

describe('clampLimit', () => {
  it('clamps to the 1–50 range', () => {
    expect(clampLimit(0)).toBe(1);
    expect(clampLimit(-5)).toBe(1);
    expect(clampLimit(51)).toBe(50);
    expect(clampLimit(200)).toBe(50);
  });

  it('keeps an in-range value, truncating a fraction', () => {
    expect(clampLimit(10)).toBe(10);
    expect(clampLimit(10.9)).toBe(10);
  });

  it('defaults a non-numeric value rather than parsing it', () => {
    expect(clampLimit(Number.NaN)).toBe(10);
    expect(clampLimit(undefined)).toBe(10);
    // A string is never parsed — '25' does not become 25, it falls back to
    // the default (which happens to also be 10, so this only proves the
    // point together with the assertion above).
    expect(clampLimit('25')).toBe(10);
  });
});

describe('isValidFilterTerm', () => {
  it('accepts empty (no filter)', () => {
    expect(isValidFilterTerm('')).toBe(true);
    expect(isValidFilterTerm('   ')).toBe(true);
  });

  it('accepts a well-formed term for every known op', () => {
    expect(isValidFilterTerm('status:eq:paid')).toBe(true);
    expect(isValidFilterTerm('price:gt:10')).toBe(true);
    expect(isValidFilterTerm('tags:in:a,b,c')).toBe(true);
  });

  it('does not truncate a value carrying its own colon', () => {
    expect(isValidFilterTerm('published_at:gte:2026-01-01T00:00:00+00:00')).toBe(true);
  });

  it('accepts is_null with an empty value (true/false lives after the op)', () => {
    expect(isValidFilterTerm('archived:is_null:true')).toBe(true);
  });

  it('rejects a field name that is not a valid identifier', () => {
    expect(isValidFilterTerm('Status:eq:paid')).toBe(false);
    expect(isValidFilterTerm('1field:eq:paid')).toBe(false);
  });

  it('rejects an unknown operator', () => {
    expect(isValidFilterTerm('status:matches:paid')).toBe(false);
  });

  it('rejects too few parts', () => {
    expect(isValidFilterTerm('status:eq')).toBe(false);
    expect(isValidFilterTerm('status')).toBe(false);
  });

  it('rejects an empty value for an op other than is_null', () => {
    expect(isValidFilterTerm('status:eq:')).toBe(false);
  });
});

describe('isValidSortTerm', () => {
  it('accepts empty, a bare field, and a descending field', () => {
    expect(isValidSortTerm('')).toBe(true);
    expect(isValidSortTerm('published_at')).toBe(true);
    expect(isValidSortTerm('-published_at')).toBe(true);
  });

  it('rejects a malformed field name', () => {
    expect(isValidSortTerm('Published_At')).toBe(false);
    expect(isValidSortTerm('-1x')).toBe(false);
  });
});

describe('buildPublicListUrl', () => {
  it('builds the base URL with just page_size when filter/sort are empty', () => {
    expect(buildPublicListUrl({ typeKey: 'products', limit: 5 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/products?page_size=5`,
    );
  });

  it('normalises a prefix with a trailing slash', () => {
    expect(
      buildPublicListUrl({ prefix: '/api/records/public/', typeKey: 'products', limit: 5 }),
    ).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=5`);
  });

  it('uses a custom prefix verbatim (normalised)', () => {
    expect(buildPublicListUrl({ prefix: '/site/data', typeKey: 'faq', limit: 25 })).toBe(
      '/site/data/faq?page_size=25',
    );
  });

  it('URL-encodes the type key', () => {
    expect(buildPublicListUrl({ typeKey: 'a b', limit: 10 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/a%20b?page_size=10`,
    );
  });

  it('adds filter and sort only when given', () => {
    const url = buildPublicListUrl({
      typeKey: 'products',
      limit: 10,
      filter: 'status:eq:paid',
      sort: '-published_at',
    });
    const parsed = new URL(url, 'http://example.test');
    expect(parsed.pathname).toBe(`${DEFAULT_PUBLIC_PREFIX}/products`);
    expect(parsed.searchParams.get('page_size')).toBe('10');
    expect(parsed.searchParams.get('filter')).toBe('status:eq:paid');
    expect(parsed.searchParams.get('sort')).toBe('-published_at');
  });

  it('omits filter/sort when blank or whitespace-only', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, filter: '  ', sort: '' });
    expect(url).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=10`);
  });

  it('clamps an out-of-range limit before building the query', () => {
    expect(buildPublicListUrl({ typeKey: 'products', limit: 999 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/products?page_size=50`,
    );
  });

  it('adds locale only when given', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, locale: 'de' });
    const parsed = new URL(url, 'http://example.test');
    expect(parsed.searchParams.get('locale')).toBe('de');
  });

  it('omits locale when blank or whitespace-only', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, locale: '  ' });
    expect(url).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=10`);
  });
});
