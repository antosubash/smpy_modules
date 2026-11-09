// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { ImportMapping } from '../../utils/importTypes';
import { stagedJob } from './fixture';
import { MappingTable } from './MappingTable';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('MappingTable', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  function render(
    mapping: ImportMapping,
    tags: 'present' | 'creatable' | 'missing' = 'present',
    onChange: (m: ImportMapping) => void = () => {},
  ) {
    const job = stagedJob();
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() =>
      root.render(
        createElement(MappingTable, {
          columns: job.columns,
          targets: { ...job.targets, tags },
          mapping,
          onChange,
        }),
      ),
    );
  }
  const select = (name: string) =>
    document.querySelector(`select[aria-label="${name}"]`) as HTMLSelectElement;
  const option = (sel: HTMLSelectElement, value: string) =>
    [...sel.options].find((o) => o.value === value) as HTMLOptionElement;

  it('disables a chosen field in the other columns', () => {
    render({ fields: { '0': 'first_name' }, tags: false });
    expect(option(select('First Name'), 'first_name').disabled).toBe(true);
    expect(option(select('Email Address'), 'first_name').disabled).toBe(false);
    expect(option(select('First Name'), '').textContent).toBe(en.import.not_imported);
  });

  it('reports a choice, keyed by the column index', () => {
    const onChange = vi.fn();
    render({ fields: {}, tags: false }, 'present', onChange);
    const sel = select('Email Address');
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set;
      set?.call(sel, 'email');
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith({ fields: { '0': 'email' }, tags: false });
  });

  it('disables the tags switch with a hint when the list has no tags field', () => {
    render({ fields: {}, tags: false }, 'missing');
    const sw = document.querySelector('[role="switch"]') as HTMLElement;
    expect(sw.hasAttribute('disabled')).toBe(true);
    expect(document.body.textContent).toContain(en.import.tags_missing_hint);
  });

  it('keeps the tags switch usable when the list can get a tags field', () => {
    render({ fields: {}, tags: false }, 'creatable');
    const sw = document.querySelector('[role="switch"]') as HTMLElement;
    expect(sw.hasAttribute('disabled')).toBe(false);
    expect(document.body.textContent).not.toContain(en.import.tags_missing_hint);
  });
});
