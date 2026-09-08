import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Byline } from './Byline';

/** The byline is a link or it is plain text — never a link to nowhere.
 *
 * `renderToStaticMarkup` rather than a DOM: vitest runs in the `node`
 * environment here, and the whole question is whether an `<a>` is in the output
 * at all, which is a string question.
 *
 * The server-side half of this is
 * `test_author_archive.py::TestTheBylineOnTheArticle`, which pins when
 * `author_url` is null. This pins what the screen does with that null — the
 * step where a dead link would actually slip through.
 */
describe('Byline', () => {
  it('links the byline when it has an address', () => {
    const html = renderToStaticMarkup(
      <Byline author="Anto Subash" url="/news/author/anto-subash" />,
    );

    expect(html).toContain('href="/news/author/anto-subash"');
    expect(html).toContain('Anto Subash');
  });

  it('renders no anchor at all when the byline has no address', () => {
    // Not an `<a>` with an empty href: a byline in a script that leaves nothing
    // to slugify has no archive page, and something that looks clickable and
    // is not is worse than the plain text this replaced.
    const html = renderToStaticMarkup(<Byline author="田中太郎" url={null} />);

    expect(html).not.toContain('<a');
    expect(html).toContain('田中太郎');
  });

  it('renders no anchor when the prop is missing entirely', () => {
    expect(renderToStaticMarkup(<Byline author="Anto Subash" />)).not.toContain('<a');
  });

  it('shows a date on its own', () => {
    const html = renderToStaticMarkup(<Byline dated="1 March 2026" />);

    expect(html).toContain('1 March 2026');
    expect(html).not.toContain('·');
  });

  it('separates the two only when both are there', () => {
    expect(renderToStaticMarkup(<Byline author="Anto Subash" dated="1 March 2026" />)).toContain(
      '·',
    );
  });

  it('renders nothing when there is neither', () => {
    // An empty line of muted text under a headline reads as a failed load.
    expect(renderToStaticMarkup(<Byline />)).toBe('');
  });
});
