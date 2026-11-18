// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { cleanHtml, safeHref } from './richtext';

describe('client rich text allow-list', () => {
  it('keeps the allowed markup and renames b and i', () => {
    expect(cleanHtml('<p>Hi <b>there</b> <i>you</i></p><h2>Head</h2><ul><li>a</li></ul>')).toBe(
      '<p>Hi <strong>there</strong> <em>you</em></p><h2>Head</h2><ul><li>a</li></ul>',
    );
  });
  it('makes hostile input inert', () => {
    const dirty =
      '<p onclick="x()">a<img src=x onerror=alert(1)><script>alert(1)</script></p>' +
      '<a href="javascript:alert(1)" style="x">l</a>' +
      '<a href=" jav&#x09;ascript:alert(1)">m</a><span style="color:red">s</span>';
    const clean = cleanHtml(dirty);
    expect(clean).toBe('<p>a</p><a>l</a><a>m</a>s');
    expect(clean).not.toMatch(/onclick|onerror|script|javascript|style/i);
    expect(cleanHtml('<svg><script>1</script></svg><p>after</p>')).not.toMatch(/svg|script|1/);
  });
  it('keeps http, https and mailto links only', () => {
    expect(cleanHtml('<a href="https://x.test/a?b=1" target="_blank">x</a>')).toBe(
      '<a href="https://x.test/a?b=1">x</a>',
    );
    expect(cleanHtml('<a href="mailto:a@b.test">x</a>')).toBe('<a href="mailto:a@b.test">x</a>');
    expect(cleanHtml('<a href="/relative">x</a><a href="data:text/html,1">y</a>')).toBe(
      '<a>x</a><a>y</a>',
    );
    expect(safeHref('  HTTPS://x.test')).toBe('HTTPS://x.test');
    expect(safeHref('java\nscript:1')).toBeNull();
  });
  it('is idempotent and survives deep nesting', () => {
    const deep = `${'<blockquote>'.repeat(40)}deep${'</blockquote>'.repeat(40)}`;
    const once = cleanHtml(deep);
    expect(cleanHtml(once)).toBe(once);
    expect(once).toContain('deep');
    expect(once.split('<blockquote>').length - 1).toBeLessThanOrEqual(20);
  });
  it('turns blank content into the empty string', () => {
    expect(cleanHtml('<p><br></p>')).toBe('');
    expect(cleanHtml('')).toBe('');
    expect(cleanHtml('<div>x</div>')).toBe('<p>x</p>');
  });
});
