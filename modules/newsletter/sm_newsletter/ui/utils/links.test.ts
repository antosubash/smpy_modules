import { describe, expect, it } from 'vitest';

import { isAllowedLink, normalizeLink } from './links';

describe('normalizeLink', () => {
  it('keeps what the server allows', () => {
    expect(normalizeLink(' https://example.com/a?b=1 ')).toBe('https://example.com/a?b=1');
    expect(normalizeLink('mailto:a@example.com')).toBe('mailto:a@example.com');
    expect(normalizeLink('/p/about')).toBe('/p/about');
  });

  it('empty input removes the link', () => {
    expect(normalizeLink('   ')).toBe('');
  });

  it('completes a bare domain or address', () => {
    expect(normalizeLink('example.com/x')).toBe('https://example.com/x');
    expect(normalizeLink('a@example.com')).toBe('mailto:a@example.com');
  });

  it('refuses what the server would strip', () => {
    for (const bad of [
      'javascript:alert(1)',
      'http://',
      '//evil.com',
      'a b',
      'https://a.com/{{x}}',
      'ftp://a.com',
      'nonsense',
    ]) {
      expect(normalizeLink(bad)).toBeNull();
    }
    expect(isAllowedLink('mailto:')).toBe(false);
    expect(isAllowedLink(`https://a.com/${'x'.repeat(2000)}`)).toBe(false);
  });
});
