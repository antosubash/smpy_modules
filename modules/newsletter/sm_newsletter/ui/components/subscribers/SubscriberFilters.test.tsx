// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { ListField, Segment } from '../../utils/types';
import { SubscriberFilters } from './SubscriberFilters';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const tags: ListField = {
  key: 'tags',
  label: 'Tags',
  type: 'choice',
  many: true,
  choices: [{ value: 'vip', label: 'VIP' }],
  system: false,
  ops: ['any'],
};
const city: ListField = { ...tags, key: 'city', label: 'City', choices: [] };
const segment: Segment = {
  id: 3,
  name: 'Active',
  list_type_key: 'news',
  rules: [],
  updated_at: null,
};

describe('SubscriberFilters', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  function render(fields: ListField[]) {
    const props = {
      q: '',
      tag: '',
      segment: '',
      fields,
      segments: [segment],
      onQ: vi.fn(),
      onTag: vi.fn(),
      onSegment: vi.fn(),
    };
    root = createRoot(document.body.appendChild(document.createElement('div')));
    act(() => root.render(createElement(SubscriberFilters, props)));
    return props;
  }
  const byLabel = (label: string) => document.querySelector(`[aria-label="${label}"]`);

  it('hides the tag select without a tags field', () => {
    render([city]);
    expect(byLabel(en.subscribers.tag_label)).toBeNull();
    expect(byLabel(en.subscribers.search_label)).not.toBeNull();
    expect(byLabel(en.subscribers.segment_label)).not.toBeNull();
  });

  it('caps the search text at the length the API accepts', () => {
    render([city]);
    const input = byLabel(en.subscribers.search_label) as HTMLInputElement;
    expect(input.maxLength).toBe(200);
  });

  it('offers the tag choices and reports a pick', () => {
    const props = render([tags]);
    const select = byLabel(en.subscribers.tag_label) as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual([en.subscribers.tag_all, 'VIP']);
    act(() => {
      select.value = 'vip';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(props.onTag).toHaveBeenCalledWith('vip');
  });
});
