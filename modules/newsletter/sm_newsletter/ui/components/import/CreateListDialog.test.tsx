// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { CreateListDialog } from './CreateListDialog';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('CreateListDialog', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  const onCreated = vi.fn();

  beforeEach(() => {
    onCreated.mockReset();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() =>
      root.render(
        createElement(CreateListDialog, { open: true, onOpenChange: () => {}, onCreated }),
      ),
    );
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  const byLabel = (text: string) => {
    const l = [...document.querySelectorAll('label')].find((x) => x.textContent === text);
    return document.getElementById(l?.getAttribute('for') ?? '') as HTMLInputElement;
  };
  const type = (el: HTMLInputElement, value: string) =>
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      set?.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  const create = () =>
    [...document.querySelectorAll('button')].find(
      (b) => b.textContent === en.import.new_list_dialog.create,
    ) as HTMLButtonElement;

  it('derives the key from the name until the key is edited', () => {
    const dlg = en.import.new_list_dialog;
    type(byLabel(dlg.label), 'Spring Sale 2026!');
    expect(byLabel(dlg.key).value).toBe('spring_sale_2026');
    type(byLabel(dlg.key), 'mine');
    type(byLabel(dlg.label), 'Other name');
    expect(byLabel(dlg.key).value).toBe('mine');
  });

  it('creates the list and reports it', async () => {
    fetchMock.mockResolvedValue(reply(201, { key: 'spring' }));
    const dlg = en.import.new_list_dialog;
    type(byLabel(dlg.label), 'Spring');
    await act(async () => create().click());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe('/api/newsletter/lists');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      key: 'spring',
      label: 'Spring',
    });
    expect(onCreated).toHaveBeenCalledWith('spring');
  });

  it('shows a taken key translated', async () => {
    fetchMock.mockResolvedValue(reply(409, { detail: 'exists', code: 'list_exists' }));
    type(byLabel(en.import.new_list_dialog.label), 'Spring');
    await act(async () => create().click());
    expect(document.body.textContent).toContain(en.errors.list_exists);
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('posts once when Create is clicked five times in one tick', async () => {
    fetchMock.mockResolvedValue(reply(201, { key: 'spring' }));
    type(byLabel(en.import.new_list_dialog.label), 'Spring');
    await act(async () => {
      for (let i = 0; i < 5; i++) create().click();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears the server error once the name or key is edited', async () => {
    fetchMock.mockResolvedValue(reply(409, { detail: 'exists', code: 'list_exists' }));
    const dlg = en.import.new_list_dialog;
    type(byLabel(dlg.label), 'Spring');
    await act(async () => create().click());
    expect(document.body.textContent).toContain(en.errors.list_exists);
    type(byLabel(dlg.key), 'spring2');
    expect(document.body.textContent).not.toContain(en.errors.list_exists);
  });

  it('cannot be submitted without a valid key', () => {
    type(byLabel(en.import.new_list_dialog.label), '!!!');
    expect(create().disabled).toBe(true);
  });
});
