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

  it('nests under a bullet that sits left of the first one', () => {
    const [list] = parseMarkdownBlocks('  - a\n- b\n  - c');
    expect(list).toEqual({
      type: 'ul',
      items: [
        { text: 'a', children: [] },
        { text: 'b', children: [{ text: 'c', children: [] }] },
      ],
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

describe('parseMarkdownBlocks numbered lists', () => {
  it('parses `1.` lines as an ordered list', () => {
    expect(parseMarkdownBlocks('1. a\n2. b')).toEqual([
      {
        type: 'ol',
        items: [
          { text: 'a', children: [] },
          { text: 'b', children: [] },
        ],
      },
    ]);
  });

  it('accepts `1)` as well as `1.`', () => {
    expect(parseMarkdownBlocks('1) a\n2) b')[0]).toMatchObject({ type: 'ol' });
  });

  it('keeps a first number other than 1 as the start', () => {
    expect(parseMarkdownBlocks('3. c\n4. d')[0]).toMatchObject({ type: 'ol', start: 3 });
    expect(parseMarkdownBlocks('1. a')[0]).not.toHaveProperty('start');
  });

  it('nests a numbered list under a bullet', () => {
    const [list] = parseMarkdownBlocks('- a\n  1. a1\n  2. a2\n- b');
    expect(list).toEqual({
      type: 'ul',
      items: [
        {
          text: 'a',
          childrenOrdered: true,
          children: [
            { text: 'a1', children: [] },
            { text: 'a2', children: [] },
          ],
        },
        { text: 'b', children: [] },
      ],
    });
  });

  it('nests bullets under a numbered item', () => {
    const [list] = parseMarkdownBlocks('1. a\n   - a1\n2. b');
    expect(list).toEqual({
      type: 'ol',
      items: [
        { text: 'a', children: [{ text: 'a1', children: [] }] },
        { text: 'b', children: [] },
      ],
    });
  });

  it('gives a nested list the kind of its first item', () => {
    const [list] = parseMarkdownBlocks('- a\n  - a1\n  1. a2');
    expect(list).toMatchObject({ items: [{ children: [{ text: 'a1' }, { text: 'a2' }] }] });
    expect(list).not.toHaveProperty('items.0.childrenOrdered');
  });

  it('starts a new list when the outermost marker kind switches', () => {
    expect(parseMarkdownBlocks('- a\n1. b\n2. c\n- d').map((b) => b.type)).toEqual([
      'ul',
      'ol',
      'ul',
    ]);
  });

  it('keeps a wrapped line that starts with a year inside its paragraph', () => {
    expect(parseMarkdownBlocks('We were founded in\n2019. Since then we grew.')).toEqual([
      { type: 'p', text: 'We were founded in 2019. Since then we grew.' },
    ]);
    expect(parseMarkdownBlocks('Steps\n1. one\n2. two').map((b) => b.type)).toEqual(['p', 'ol']);
  });

  it('leaves a number without a following space as a paragraph', () => {
    expect(parseMarkdownBlocks('2026.')[0]).toEqual({ type: 'p', text: '2026.' });
  });
});

describe('markdownToHtml numbered lists', () => {
  it('emits <ol>, with start only when it is not 1', () => {
    expect(markdownToHtml('1. a\n2. b')).toBe('<ol><li>a</li><li>b</li></ol>');
    expect(markdownToHtml('3. c')).toBe('<ol start="3"><li>c</li></ol>');
  });

  it('nests an <ol> inside a bullet', () => {
    expect(markdownToHtml('- a\n  1. a1')).toBe('<ul><li>a<ol><li>a1</li></ol></li></ul>');
  });
});
