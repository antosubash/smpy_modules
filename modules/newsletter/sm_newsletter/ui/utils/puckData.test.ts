import type { Data } from '@puckeditor/core';
import { describe, expect, it } from 'vitest';

import { fromPuckData, toPuckData } from './puckData';
import type { Block } from './types';

const body: Block[] = [
  { type: 'Heading', props: { id: 'h1', text: 'Hello', level: 2 } },
  { type: 'Divider', props: { id: 'd1' } },
];

describe('puckData', () => {
  it('round-trips content and drops root', () => {
    const data = toPuckData(body);
    expect(data.content).toHaveLength(2);
    expect(fromPuckData(data)).toEqual(body);

    const edited: Data = {
      root: { props: { title: 'ignored' } },
      content: [{ type: 'Spacer', props: { id: 's1', height: 8 } }],
      zones: { z: [] },
    };
    expect(fromPuckData(edited)).toEqual([{ type: 'Spacer', props: { id: 's1', height: 8 } }]);
  });

  it('does not share props objects with the body', () => {
    const data = toPuckData(body);
    (data.content[0].props as Record<string, unknown>).text = 'changed';
    expect(body[0].props.text).toBe('Hello');
  });

  it('maps an empty body to empty content', () => {
    expect(toPuckData([]).content).toEqual([]);
  });
});
