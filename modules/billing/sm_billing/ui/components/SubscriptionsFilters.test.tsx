// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SubjectMode } from '../utils/types';
import { SubscriptionsFilters } from './SubscriptionsFilters';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function type(el: HTMLInputElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('SubscriptionsFilters', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
  });

  async function mount(opts: { search?: string; mode?: SubjectMode } = {}) {
    const onChange = vi.fn();
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <SubscriptionsFilters
          status=""
          search={opts.search ?? ''}
          subjectMode={opts.mode ?? 'tenant'}
          onChange={onChange}
        />,
      );
    });
    const input = document.querySelector<HTMLInputElement>('#subscriptions-search');
    if (!input) throw new Error('no search input');
    return { onChange, input };
  }

  it('submits the trimmed search with the status kept', async () => {
    const { onChange, input } = await mount();
    await act(async () => type(input, '  alice@x.io '));
    await act(async () => {
      document.querySelector<HTMLFormElement>('form')?.requestSubmit();
    });
    expect(onChange).toHaveBeenCalledWith({ status: '', q: 'alice@x.io' });
  });

  it('starts from the current search and names what it searches per mode', async () => {
    const { input } = await mount({ search: 'acme' });
    expect(input.value).toBe('acme');
    expect(input.placeholder).toBe('Name, slug or ID');
    act(() => root?.unmount());
    host?.remove();
    const user = await mount({ mode: 'user' });
    expect(user.input.placeholder).toBe('Email or ID');
  });
});
