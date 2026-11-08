// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { COUNT_DEBOUNCE_MS } from '../../hooks/useAudienceCount';
import type { ListField, Segment } from '../../utils/types';
import { SegmentEditorDialog } from './SegmentEditorDialog';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.segments;
const fields: ListField[] = [
  {
    key: 'city',
    label: 'City',
    type: 'text',
    many: false,
    choices: [],
    system: false,
    ops: ['is', 'contains'],
  },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('SegmentEditorDialog', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  const onSaved = vi.fn();
  let next: () => Response;

  beforeEach(() => {
    onSaved.mockReset();
    next = () => json({ count: 5 });
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/segments/preview')) {
        const n = (JSON.parse(String(init?.body)).rules as unknown[]).length;
        return json({ count: 5 + n });
      }
      return next();
    });
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  const wait = (ms: number) =>
    act(async () => {
      await new Promise((r) => setTimeout(r, ms));
    });
  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
      | HTMLButtonElement
      | undefined;
  const draw = (segment: Segment | null, isOpen: boolean, canCount = true) =>
    act(async () =>
      root.render(
        createElement(SegmentEditorDialog, {
          listKey: 'news',
          segment,
          fields,
          open: isOpen,
          onOpenChange: vi.fn(),
          onSaved,
          canCount,
        }),
      ),
    );
  async function open(segment: Segment | null = null) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await draw(segment, true);
    await wait(COUNT_DEBOUNCE_MS + 100);
  }
  async function type(el: HTMLInputElement, value: string) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }
  const previews = () =>
    fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/segments/preview'));
  const rows = () => document.querySelectorAll('[data-rule-row]');
  const saveCalls = () =>
    fetchMock.mock.calls.filter(([u]) => !String(u).endsWith('/segments/preview'));

  it('asks for no preview count without records.view', async () => {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await draw(null, true, false);
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(previews()).toEqual([]);
    expect(document.body.textContent).toContain(en.audience.count_hidden);
    expect(document.body.textContent).not.toContain(copy.count_loading);
  });

  it('updates the preview count after an edit', async () => {
    await open();
    expect(document.body.textContent).toContain('About 5 subscribers match');
    await act(async () => button(copy.add_rule)?.click());
    await type(document.querySelector('input[aria-label="Value"]') as HTMLInputElement, 'Berlin');
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(document.body.textContent).toContain('About 6 subscribers match');
  });

  it('saves {name, list_type_key, rules}', async () => {
    next = () =>
      json({ id: 1, name: 'Berliners', list_type_key: 'news', rules: [], updated_at: null }, 201);
    await open();
    await type(document.getElementById('newsletter-segment-name') as HTMLInputElement, 'Berliners');
    await act(async () => button(copy.add_rule)?.click());
    await type(document.querySelector('input[aria-label="Value"]') as HTMLInputElement, 'Berlin');
    await act(async () => button(copy.save)?.click());
    const [url, init] = saveCalls()[0] as [string, RequestInit];
    expect(url).toBe('/api/newsletter/segments');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      name: 'Berliners',
      list_type_key: 'news',
      rules: [{ field: 'city', op: 'is', value: 'Berlin' }],
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('highlights the row a 422 names', async () => {
    next = () => json({ detail: 'rules[1]: value must be a number', code: 'invalid_segment' }, 422);
    await open();
    await type(document.getElementById('newsletter-segment-name') as HTMLInputElement, 'S');
    await act(async () => button(copy.add_rule)?.click());
    await act(async () => button(copy.add_rule)?.click());
    await act(async () => button(copy.save)?.click());
    const marks = [...rows()].map((r) => r.getAttribute('data-invalid'));
    expect(marks).toEqual(['false', 'true']);
    expect(document.body.textContent).toContain(en.errors.invalid_segment);
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('disables Add rule at ten rules', async () => {
    await open();
    for (let i = 0; i < 10; i++) await act(async () => button(copy.add_rule)?.click());
    expect(rows().length).toBe(10);
    expect(button(copy.add_rule)?.disabled).toBe(true);
  });

  it('asks nothing while closed', async () => {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await draw(null, false);
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(previews()).toHaveLength(0);
  });

  it('shows the loading copy, not the old count, on reopen', async () => {
    await open();
    expect(document.body.textContent).toContain('About 5 subscribers match');
    await draw(null, false);
    await draw(null, true);
    expect(document.body.textContent).toContain(copy.count_loading);
    expect(document.body.textContent).not.toContain('About 5 subscribers match');
  });

  it('highlights the row a preview 422 names, past an incomplete row', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      String(url).endsWith('/segments/preview')
        ? json({ detail: 'rules[0]: value must be a number', code: 'invalid_segment' }, 422)
        : next(),
    );
    const segment: Segment = {
      id: 1,
      name: 'S',
      list_type_key: 'news',
      rules: [
        { field: 'city', op: 'is', value: '' },
        { field: 'city', op: 'is', value: 'x' },
      ],
      updated_at: null,
    };
    await open(segment);
    const marks = [...rows()].map((r) => r.getAttribute('data-invalid'));
    expect(marks).toEqual(['false', 'true']);
  });

  it('says incomplete rules are not counted', async () => {
    await open();
    expect(document.body.textContent).not.toContain(copy.count_incomplete);
    await act(async () => button(copy.add_rule)?.click());
    expect(document.body.textContent).toContain(copy.count_incomplete);
    await type(document.querySelector('input[aria-label="Value"]') as HTMLInputElement, 'Berlin');
    expect(document.body.textContent).not.toContain(copy.count_incomplete);
  });
});
