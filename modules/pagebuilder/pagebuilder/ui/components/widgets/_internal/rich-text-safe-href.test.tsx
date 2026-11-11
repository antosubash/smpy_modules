import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

// Bypass `splitLinks`' own filter: the anchor must refuse the href by itself.
vi.mock('../../../utils/markdown-links', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../utils/markdown-links')>()),
  splitLinks: (text: string) => [{ type: 'link', label: 'click', href: text }],
}));

const { RichTextBlock } = await import('./rich-text');

const html = (text: string) => renderToStaticMarkup(<RichTextBlock text={text} />);

describe('RichTextBlock anchors', () => {
  it('renders an unsafe href as # (#354)', () => {
    expect(html('javascript:alert(1)')).toContain('href="#"');
    expect(html('javascript:alert(1)')).not.toContain('javascript:');
  });

  it('keeps a safe href', () => {
    expect(html('https://example.com/a')).toContain('href="https://example.com/a"');
  });
});
