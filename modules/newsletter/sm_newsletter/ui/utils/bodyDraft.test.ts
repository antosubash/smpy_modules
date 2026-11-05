import { describe, expect, it } from 'vitest';

import { bodyKey, isComplete, normalizeBody } from './bodyDraft';

describe('bodyDraft', () => {
  it('requires the fields content/blocks.py requires', () => {
    expect(isComplete({ type: 'Image', props: { id: 'a', src: ' ' } })).toBe(false);
    expect(isComplete({ type: 'Image', props: { id: 'a', src: '/x.png' } })).toBe(true);
    expect(isComplete({ type: 'Button', props: { id: 'b', label: 'Go', href: '' } })).toBe(false);
    expect(isComplete({ type: 'PageCard', props: { id: 'c', source_id: 0, url: '' } })).toBe(false);
    expect(isComplete({ type: 'PageCard', props: { id: 'c', source_id: 3, url: '/p' } })).toBe(
      true,
    );
    expect(isComplete({ type: 'Divider', props: { id: 'd' } })).toBe(true);
  });

  it('omits an empty image link and a cleared width', () => {
    const [image] = normalizeBody([
      { type: 'Image', props: { id: 'a', src: '/x.png', alt: '', href: '', width: Number.NaN } },
    ]);
    expect(image.props).toEqual({ id: 'a', src: '/x.png', alt: '' });
  });
});

describe('bodyKey', () => {
  it('ignores key order', () => {
    expect(bodyKey([{ type: 'Heading', props: { text: 'A', id: 'h' } }])).toBe(
      bodyKey([{ props: { id: 'h', text: 'A' }, type: 'Heading' }]),
    );
    expect(bodyKey([{ type: 'Heading', props: { id: 'h', text: 'A' } }])).not.toBe(
      bodyKey([{ type: 'Heading', props: { id: 'h', text: 'B' } }]),
    );
  });
});
