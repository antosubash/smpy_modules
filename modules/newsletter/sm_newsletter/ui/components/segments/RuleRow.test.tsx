// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { ListField, Rule } from '../../utils/types';
import { RuleRow } from './RuleRow';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.segments;
const fields: ListField[] = [
  {
    key: 'tags',
    label: 'Tags',
    type: 'select',
    many: true,
    choices: [
      { value: 'vip', label: 'VIP' },
      { value: 'beta', label: 'Beta' },
    ],
    system: false,
    ops: ['any', 'all', 'none'],
  },
  {
    key: 'city',
    label: 'City',
    type: 'text',
    many: false,
    choices: [],
    system: false,
    ops: ['is', 'is_not', 'contains', 'starts_with'],
  },
  {
    key: 'created_at',
    label: 'Signed up',
    type: 'datetime',
    many: false,
    choices: [],
    system: true,
    ops: ['before', 'since'],
  },
];

describe('RuleRow', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(rule: Rule, onChange = vi.fn()) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(RuleRow, { rule, fields, onChange, onRemove: vi.fn(), disabled: false }),
      ),
    );
    return onChange;
  }
  const select = (label: string) =>
    document.querySelector(`select[aria-label="${label}"]`) as HTMLSelectElement;
  async function choose(el: HTMLSelectElement, value: string) {
    await act(async () => {
      el.value = value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  it('resets the op and the value when the field changes', async () => {
    const onChange = await render({ field: 'city', op: 'contains', value: 'Ber' });
    await choose(select(copy.field), 'tags');
    expect(onChange).toHaveBeenCalledWith({ field: 'tags', op: 'any', value: [] });
  });

  it('offers exactly any, all and none for a many field', async () => {
    await render({ field: 'tags', op: 'any', value: [] });
    const ops = [...select(copy.op).options].map((o) => o.textContent);
    expect(ops).toEqual([copy.ops.any, copy.ops.all, copy.ops.none]);
  });

  it('renders a date input for a date field, labelled by the catalogue', async () => {
    await render({ field: 'created_at', op: 'since', value: '' });
    expect((document.querySelector('input') as HTMLInputElement).type).toBe('date');
    expect([...select(copy.field).options].map((o) => o.textContent)).toContain(copy.signup_field);
  });

  it('clears the value when the op switches between a list and a single value', async () => {
    const onChange = await render({ field: 'city', op: 'is', value: 'x' });
    await choose(select(copy.op), 'contains');
    expect(onChange).toHaveBeenCalledWith({ field: 'city', op: 'contains', value: 'x' });
  });
});
