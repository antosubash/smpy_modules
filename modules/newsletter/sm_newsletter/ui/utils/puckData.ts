/** Puck's `Data` <-> the stored body (a list of blocks, no `root`, ruling R8). */

import type { Data } from '@puckeditor/core';

import type { Block } from './types';

export function toPuckData(body: Block[]): Data {
  return {
    root: { props: {} },
    content: body.map((block) => ({ type: block.type, props: { ...block.props } })),
  };
}

export function fromPuckData(data: Data): Block[] {
  return data.content.map((item) => ({
    type: item.type as Block['type'],
    props: { ...item.props } as Block['props'],
  }));
}
