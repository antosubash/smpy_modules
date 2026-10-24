// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MeterInfo } from '../utils/types';
import { AdjustDialog } from './AdjustDialog';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const METERS: MeterInfo[] = [
  { key: 'exports.monthly', kind: 'counter', unit: 'count', label_key: '' },
  { key: 'ai.requests', kind: 'counter', unit: 'count', label_key: '' },
];

/** Type into a React-controlled field: set the native value, then fire `input`. */
function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('AdjustDialog', () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
  });

  async function mount(initialMeter = '') {
    const onSubmit = vi.fn();
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <AdjustDialog
          open
          meters={METERS}
          initialMeter={initialMeter}
          busy={false}
          onClose={() => {}}
          onSubmit={onSubmit}
        />,
      );
    });
    const q = <T extends Element>(selector: string) => {
      const el = document.querySelector<T & Element>(selector);
      if (!el) throw new Error(`missing ${selector}`);
      return el;
    };
    const submit = async () => {
      await act(async () => {
        q<HTMLFormElement>('form').requestSubmit();
      });
    };
    return { onSubmit, q, submit };
  }

  it('requires a reason', async () => {
    const { onSubmit, q, submit } = await mount();
    await act(async () => type(q<HTMLInputElement>('#adjust-quantity'), '-2'));
    await act(async () => type(q<HTMLTextAreaElement>('#adjust-reason'), '   '));
    await submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('A reason is required.');
    expect(q('#adjust-reason').getAttribute('aria-invalid')).toBe('true');
  });

  it.each(['', '0', '1.5', 'abc', '--3'])('refuses quantity %j', async (text) => {
    const { onSubmit, q, submit } = await mount();
    await act(async () => type(q<HTMLInputElement>('#adjust-quantity'), text));
    await act(async () => type(q<HTMLTextAreaElement>('#adjust-reason'), 'credit'));
    await submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Enter a whole number other than 0.');
  });

  it('submits a signed quantity with the trimmed reason for the chosen meter', async () => {
    const { onSubmit, q, submit } = await mount('ai.requests');
    expect(q<HTMLSelectElement>('#adjust-meter').value).toBe('ai.requests');
    await act(async () => type(q<HTMLInputElement>('#adjust-quantity'), ' -5 '));
    await act(async () => type(q<HTMLTextAreaElement>('#adjust-reason'), '  goodwill  '));
    await submit();
    expect(onSubmit).toHaveBeenCalledWith('ai.requests', -5, 'goodwill');
  });

  it('defaults to the first counter and takes a positive charge', async () => {
    const { onSubmit, q, submit } = await mount();
    expect(q<HTMLSelectElement>('#adjust-meter').value).toBe('exports.monthly');
    await act(async () => type(q<HTMLInputElement>('#adjust-quantity'), '+3'));
    await act(async () => type(q<HTMLTextAreaElement>('#adjust-reason'), 'missed import'));
    await submit();
    expect(onSubmit).toHaveBeenCalledWith('exports.monthly', 3, 'missed import');
  });
});
