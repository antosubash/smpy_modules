// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { TagEditor } from './TagEditor';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const choices = [
  { value: 'vip', label: 'VIP' },
  { value: 'beta', label: 'Beta' },
  { value: 'press', label: 'Press' },
];

describe('TagEditor', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  function render(tags: string[], disabled = false, onSave = vi.fn(async () => {})) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() => root.render(createElement(TagEditor, { tags, choices, disabled, onSave })));
    return onSave;
  }
  const boxes = () => [...document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
  const save = () =>
    [...document.querySelectorAll('button')].find(
      (b) => b.textContent === en.subscribers.detail.tags_save,
    ) as HTMLButtonElement;
  const click = (el: Element) => act(() => (el as HTMLElement).click());

  it('offers only the choices and sends exactly the diff', async () => {
    const onSave = render(['vip']);
    expect(
      boxes().map((b) => b.getAttribute('aria-label') ?? b.parentElement?.textContent),
    ).toEqual(['VIP', 'Beta', 'Press']);
    expect(save().disabled).toBe(true);
    click(boxes()[0]); // remove vip
    click(boxes()[2]); // add press
    await act(async () => save().click());
    expect(onSave).toHaveBeenCalledWith(['press'], ['vip']);
  });

  it('is read-only when disabled', () => {
    render(['vip'], true);
    expect(boxes()).toHaveLength(0);
    expect(document.body.textContent).toContain('VIP');
    expect(save()).toBeUndefined();
  });
});
