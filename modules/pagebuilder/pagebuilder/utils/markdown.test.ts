import { describe, expect, it } from 'vitest';

import { markdownToHtml, parseMarkdownBlocks } from './markdown';

describe('parseMarkdownBlocks lists', () => {
  it('keeps a flat list flat', () => {
    expect(parseMarkdownBlocks('- a\n- b')).toEqual([
      {
        type: 'ul',
        items: [
          { text: 'a', children: [] },
          { text: 'b', children: [] },
        ],
      },
    ]);
  });

  it('nests an indented bullet under the one above it (#66)', () => {
    const [list] = parseMarkdownBlocks('- a\n  - a1\n    - a1x\n  - a2\n- b');
    expect(list).toEqual({
      type: 'ul',
      items: [
        {
          text: 'a',
          children: [
            { text: 'a1', children: [{ text: 'a1x', children: [] }] },
            { text: 'a2', children: [] },
          ],
        },
        { text: 'b', children: [] },
      ],
    });
  });

  it('counts a tab as one level of indent', () => {
    const [list] = parseMarkdownBlocks('- a\n\t- a1');
    expect(list).toEqual({
      type: 'ul',
      items: [{ text: 'a', children: [{ text: 'a1', children: [] }] }],
    });
  });

  it('starts a new list after a blank line', () => {
    expect(parseMarkdownBlocks('- a\n\n  - b').map((b) => b.type)).toEqual(['ul', 'ul']);
  });
});

describe('markdownToHtml lists', () => {
  it('emits a nested <ul> inside its parent <li>', () => {
    expect(markdownToHtml('- a\n  - **a1**\n- b')).toBe(
      '<ul><li>a<ul><li><strong>a1</strong></li></ul></li><li>b</li></ul>',
    );
  });
});
