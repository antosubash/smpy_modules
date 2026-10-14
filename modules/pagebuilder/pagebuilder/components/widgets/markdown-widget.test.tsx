import type { ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MarkdownWidget } from './markdown-widget';

const Markdown = MarkdownWidget.render as unknown as (
  props: Record<string, unknown>,
) => ReactElement;

function html(content: string): string {
  return renderToStaticMarkup(<Markdown {...MarkdownWidget.defaultProps} content={content} />);
}

// #66: content seeded from existing Markdown (a partners page of logos)
// rendered `![alt](src)` as literal text and flattened nested lists.
describe('MarkdownWidget images', () => {
  it('renders an image', () => {
    const out = html('![Acme logo](/media/acme.png)');
    expect(out).toContain('<img');
    expect(out).toContain('src="/media/acme.png"');
    expect(out).toContain('alt="Acme logo"');
    expect(out).not.toContain('![');
  });

  it('renders a linked image as an image inside the link', () => {
    const out = html('[![Acme](/media/acme.png)](https://acme.example)');
    expect(out).toMatch(
      /<a [^>]*href="https:\/\/acme\.example"[^>]*><img [^>]*src="\/media\/acme\.png"/,
    );
  });

  it('keeps several images on one line in one paragraph', () => {
    const out = html('![A](/a.png) ![B](https://cdn.example/b.png)');
    expect(out.match(/<img /g)).toHaveLength(2);
    expect(out.match(/<p /g)).toHaveLength(1);
  });

  it('accepts an empty alt', () => {
    expect(html('![](/logo.png)')).toContain('alt=""');
  });

  it('leaves an unsafe src as visible text, like an unsafe link', () => {
    for (const src of ['javascript:alert(1)', 'data:image/svg+xml,x']) {
      const out = html(`![x](${src})`);
      expect(out).not.toContain('<img');
      expect(out).toContain(`![x](${src})`);
    }
  });

  it('does not wrap an image in a link whose href is unsafe', () => {
    const out = html('[![x](/x.png)](javascript:alert(1))');
    expect(out).not.toContain('href="javascript');
  });

  it('still renders plain links', () => {
    expect(html('[Docs](/docs)')).toMatch(/<a [^>]*href="\/docs"[^>]*>Docs<\/a>/);
  });
});

describe('MarkdownWidget nested lists', () => {
  it('renders an indented bullet as a nested list', () => {
    const out = html('- Partners\n  - Gold\n  - Silver\n- Press');
    expect(out).toMatch(
      /<li>Partners<ul [^>]*><li>Gold<\/li><li>Silver<\/li><\/ul><\/li><li>Press<\/li>/,
    );
  });
});
