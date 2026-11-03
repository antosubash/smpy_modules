import { describe, expect, it } from 'vitest';

import { withBlockIds } from './blockIds';

const ids = (data: { content?: unknown }) =>
  (data.content as { props: { id: string } }[]).map((block) => block.props.id);

describe('withBlockIds', () => {
  it('hands back the same document when every block already has its own id', () => {
    const doc = { content: [{ type: 'Paragraph', props: { id: 'a' } }], root: {} };
    expect(withBlockIds(doc)).toBe(doc);
  });

  it('keeps the ids a document carries and fills the missing ones by position', () => {
    const doc = {
      content: [
        { type: 'Heading', props: { id: 'h-1', text: 'One' } },
        { type: 'Paragraph', props: { text: 'x' } },
        { type: 'Divider' },
      ],
    };
    expect(ids(withBlockIds(doc))).toEqual(['h-1', 'block-1', 'block-2']);
    // Copy-on-write: the server's prop is not touched.
    expect(doc.content[1].props).toEqual({ text: 'x' });
  });

  it('lets the first holder keep a repeated id and renames the rest', () => {
    const doc = {
      content: [
        { type: 'Heading', props: { id: 'dup' } },
        { type: 'Paragraph', props: { id: 'dup' } },
      ],
    };
    expect(ids(withBlockIds(doc))).toEqual(['dup', 'block-1']);
  });

  it('never mints an id a later block already carries', () => {
    const doc = {
      content: [
        { type: 'Paragraph', props: {} },
        { type: 'Paragraph', props: { id: 'block-0' } },
      ],
    };
    const result = ids(withBlockIds(doc));
    expect(new Set(result).size).toBe(2);
    expect(result[1]).toBe('block-0');
  });

  it('leaves a document without a content list alone', () => {
    const doc: { root: object; content?: unknown } = { root: {} };
    expect(withBlockIds(doc)).toBe(doc);
  });
});
