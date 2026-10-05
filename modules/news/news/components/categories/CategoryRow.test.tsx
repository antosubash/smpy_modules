// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { CategoryRead } from '../../utils/taxonomyApi';
import { CategoryRow } from './CategoryRow';

// `@simple-module-py/ui` is compiled against a global `React` (see records'
// `test-dom.tsx`), which happy-dom does not provide.
(globalThis as unknown as { React: unknown }).React = React;
// Lets `act` know this is a React test environment.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const category: CategoryRead = {
  id: 3,
  name: 'Politics',
  slug: 'politics',
  position: 0,
  article_count: 2,
  is_system: false,
};

/** QA (ship round 1): renaming to a name that already exists closed the row
 *  and dropped what was typed, leaving only the page banner to say why. */
describe('CategoryRow — rename', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
  });

  async function mount(onSave: (id: number, name: string, slug: string) => Promise<boolean>) {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <ul>
          <CategoryRow
            category={category}
            busy={false}
            dragging={false}
            onSave={onSave}
            onDragStart={() => {}}
            onDragOver={() => {}}
            onDrop={() => {}}
            onDragEnd={() => {}}
          />
        </ul>,
      );
    });
    const buttons = () => Array.from(host?.querySelectorAll('button') ?? []);
    const inputs = () => Array.from(host?.querySelectorAll('input') ?? []);
    // Not editing, the managed row's first action is Rename.
    await act(async () => buttons()[0]?.click());
    return { buttons, inputs };
  }

  async function typeName(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    await act(async () => {
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('stays in edit mode with the typed name when the rename is refused', async () => {
    const onSave = vi.fn(async () => false);
    const view = await mount(onSave);
    await typeName(view.inputs()[0] as HTMLInputElement, 'Economy');
    await act(async () => view.buttons()[0]?.click());
    expect(onSave).toHaveBeenCalledWith(3, 'Economy', 'politics');
    expect(view.inputs()).toHaveLength(2);
    expect((view.inputs()[0] as HTMLInputElement).value).toBe('Economy');
  });

  it('closes the editor once the rename is written', async () => {
    const view = await mount(vi.fn(async () => true));
    await typeName(view.inputs()[0] as HTMLInputElement, 'Economy');
    await act(async () => view.buttons()[0]?.click());
    expect(view.inputs()).toHaveLength(0);
  });
});
