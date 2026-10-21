// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { TagRead } from '../../utils/taxonomyApi';
import { TagPanel } from './TagPanel';

// See CategoryRow.test.tsx: the UI package expects a global `React`.
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TAGS: TagRead[] = [
  { id: 1, name: 'Urbn', slug: 'urbn', article_count: 3 },
  { id: 2, name: 'Rural', slug: 'rural', article_count: 0 },
];

type Handlers = {
  onRename?: (id: number, name: string) => Promise<boolean>;
  onDelete?: (id: number) => Promise<unknown>;
  onMerge?: (target: number, source: number) => Promise<unknown>;
};

/** #174: a tag could be created and merged, but never renamed or deleted. */
describe('TagPanel — rename and delete', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    document.body.innerHTML = '';
  });

  async function mount(handlers: Handlers = {}, tags: TagRead[] = TAGS) {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    const render = async (list: TagRead[]) =>
      act(async () => {
        root?.render(
          <TagPanel
            tags={list}
            busy={false}
            onCreate={vi.fn(async () => {})}
            onMerge={handlers.onMerge ?? vi.fn(async () => {})}
            onRename={handlers.onRename ?? vi.fn(async () => true)}
            onDelete={handlers.onDelete ?? vi.fn(async () => {})}
          />,
        );
      });
    await render(tags);
    return { render };
  }

  const chip = (name: string) =>
    Array.from(document.querySelectorAll<HTMLButtonElement>('[data-testid="tag-chip"]')).find((b) =>
      b.textContent?.startsWith(name),
    );
  const button = (label: string) =>
    Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent?.trim() === label,
    );
  const actions = () => document.querySelector('[data-testid="tag-actions"]');
  const nameInput = () => document.querySelector<HTMLInputElement>('input[aria-label="Tag name"]');

  async function click(el: HTMLElement | null | undefined) {
    expect(el).toBeTruthy();
    await act(async () => el?.click());
  }

  async function type(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    await act(async () => {
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('offers rename and delete for exactly one selected tag', async () => {
    await mount();
    expect(actions()).toBeNull();

    await click(chip('Urbn'));
    expect(actions()?.textContent).toContain('Urbn is on 3 articles');
    expect(button('Rename')).toBeTruthy();
    expect(button('Delete')).toBeTruthy();

    // Two selected is a merge, not an edit.
    await click(chip('Rural'));
    expect(actions()).toBeNull();
    expect(button('Merge')).toBeTruthy();
  });

  it('renames the selected tag and closes once written', async () => {
    const onRename = vi.fn(async () => true);
    await mount({ onRename });
    await click(chip('Urbn'));
    await click(button('Rename'));

    await type(nameInput() as HTMLInputElement, '  Urban  ');
    await click(button('Save'));

    expect(onRename).toHaveBeenCalledWith(1, 'Urban');
    expect(nameInput()).toBeNull();
  });

  it('keeps a refused rename editable with what was typed', async () => {
    const onRename = vi.fn(async () => false);
    await mount({ onRename });
    await click(chip('Urbn'));
    await click(button('Rename'));

    await type(nameInput() as HTMLInputElement, 'Rural');
    await click(button('Save'));

    expect(onRename).toHaveBeenCalledWith(1, 'Rural');
    expect(nameInput()?.value).toBe('Rural');
  });

  it('confirms a delete with how many articles lose the tag', async () => {
    const onDelete = vi.fn(async () => {});
    await mount({ onDelete });
    await click(chip('Urbn'));
    await click(button('Delete'));

    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain('Delete tag "Urbn"?');
    expect(dialog?.textContent).toContain('3 articles will lose this tag');
    expect(onDelete).not.toHaveBeenCalled();

    await click(button('Delete tag'));
    expect(onDelete).toHaveBeenCalledWith(1);
  });

  it('keeps a refused delete open with the reason in it', async () => {
    const onDelete = vi.fn(async () => {
      throw new Error('Tag not found.');
    });
    await mount({ onDelete });
    await click(chip('Urbn'));
    await click(button('Delete'));
    await click(button('Delete tag'));

    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('Tag not found.');
  });

  it('says nothing else changes when the tag is unused', async () => {
    await mount();
    await click(chip('Rural'));
    await click(button('Delete'));

    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain('No article uses this tag');
  });

  it('drops a selection whose tag is gone after a refresh', async () => {
    const view = await mount();
    await click(chip('Urbn'));
    expect(actions()).not.toBeNull();

    await view.render([TAGS[1]]);
    expect(actions()).toBeNull();

    // And the vanished id does not pair with the next pick into a merge.
    await click(chip('Rural'));
    expect(actions()?.textContent).toContain('Rural is on 0 articles');
    expect(button('Merge')).toBeUndefined();
  });

  it("does not pre-select a new tag that reuses a deleted one's id", async () => {
    const view = await mount();
    await click(chip('Urbn'));
    await view.render([TAGS[1]]);

    // SQLite hands the next tag the freed id.
    await view.render([TAGS[1], { id: 1, name: 'Fresh', slug: 'fresh', article_count: 0 }]);
    expect(chip('Fresh')?.getAttribute('aria-pressed')).toBe('false');
    expect(actions()).toBeNull();
  });

  it('Escape cancels an inline rename', async () => {
    const onRename = vi.fn(async () => true);
    await mount({ onRename });
    await click(chip('Urbn'));
    await click(button('Rename'));

    const input = nameInput() as HTMLInputElement;
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(nameInput()).toBeNull();
    expect(onRename).not.toHaveBeenCalled();
  });
});
