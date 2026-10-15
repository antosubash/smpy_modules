import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { RichTextBlock } from './rich-text';

const html = (text: string, className?: string) =>
  renderToStaticMarkup(<RichTextBlock text={text} className={className} />);

describe('RichTextBlock', () => {
  it('lets a long unbroken word wrap, alone or among blocks', () => {
    const url = `https://example.com/${'x'.repeat(120)}`;
    expect(html(url, 'text-sm')).toMatch(/^<p class="\[overflow-wrap:anywhere\] text-sm">/);
    expect(html(`${url}\n\n- a`)).toMatch(/^<div class="\[overflow-wrap:anywhere\]">/);
  });

  it('renders a numbered list with decimal markers', () => {
    expect(html('Steps:\n\n2. b\n3. c')).toMatch(
      /<ol class="list-decimal [^"]*" start="2"><li>b<\/li><li>c<\/li><\/ol>/,
    );
  });
});
