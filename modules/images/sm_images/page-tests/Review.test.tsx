// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, click, press, setValue } from '../test-dom';
import { item, LIST, open, posts, reviewed, shown } from './reviewSupport';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

describe('review queue', () => {
  it('j and k move through the queue', async () => {
    const { view } = await open({ [LIST]: { items: [item(1), item(2), item(3)], next_cursor: null } });
    expect(shown(view)).toBe('1');
    await press(window, { key: 'j' });
    await press(window, { key: 'j' });
    expect(shown(view)).toBe('3');
    await press(window, { key: 'j' }); // the end stays
    expect(shown(view)).toBe('3');
    await press(window, { key: 'k' });
    expect(shown(view)).toBe('2');
    await view.unmount();
  });

  it('a accepts and r rejects the shown result, which leaves the queue', async () => {
    const { view, calls } = await open({
      [LIST]: { items: [item(1), item(2)], next_cursor: null },
      [reviewed(1)]: { item: item(1, { review_status: 'accepted' }) },
      [reviewed(2)]: { item: item(2, { review_status: 'rejected' }) },
    });
    await press(window, { key: 'a' });
    await act(async () => {});
    expect(posts(calls)).toEqual([{ action: 'accept', version: 'v1' }]);
    expect(shown(view)).toBe('2');
    await press(window, { key: 'r' });
    await act(async () => {});
    expect(posts(calls).at(-1)).toEqual({ action: 'reject', version: 'v2' });
    expect(view.find('[data-testid="images-review-empty"]')).not.toBeNull();
    await view.unmount();
  });

  it('e opens the form generated from the schema; typing in it is not a shortcut', async () => {
    const { view, calls } = await open({
      [LIST]: { items: [item(1)], next_cursor: null },
      [reviewed(1)]: { item: item(1, { review_status: 'corrected' }) },
    });
    await press(window, { key: 'e' });
    const n = view.find<HTMLInputElement>('[data-testid="images-review-field-n"]');
    const kind = view.find<HTMLSelectElement>('[data-testid="images-review-field-kind"]');
    expect(n?.value).toBe('1');
    expect(kind?.tagName).toBe('SELECT');
    await press(n, { key: 'a' }); // typing, not accepting
    expect(posts(calls)).toEqual([]);
    await setValue(n as HTMLInputElement, '7');
    await setValue(kind as HTMLSelectElement, 'b');
    await click(view.find('[data-testid="images-review-save"]'));
    await act(async () => {});
    expect(posts(calls)).toEqual([{ action: 'correct', version: 'v1', data: { n: 7, kind: 'b' } }]);
    await view.unmount();
  });

  it('Escape leaves the form and a required field is checked before sending', async () => {
    const { view, calls } = await open({ [LIST]: { items: [item(1)], next_cursor: null } });
    await press(window, { key: 'e' });
    await setValue(view.find('[data-testid="images-review-field-n"]') as HTMLInputElement, '');
    await click(view.find('[data-testid="images-review-save"]'));
    expect(posts(calls)).toEqual([]);
    expect(view.host.textContent).toContain('Required');
    await press(window, { key: 'Escape' });
    expect(view.find('[data-testid="images-review-form"]')).toBeNull();
    await view.unmount();
  });

  it('a result that changed (409) reloads the queue', async () => {
    let reads = 0;
    const { view } = await open({
      [LIST]: () => ({
        items: [++reads === 1 ? item(1) : item(1, { version: 'v1b', result_data: { n: 9 } })],
        next_cursor: null,
      }),
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST') {
          return new Response(JSON.stringify({ detail: 'x', code: 'review_stale' }), { status: 409 });
        }
        const list = String(input).includes('/review');
        return new Response(
          JSON.stringify(
            list
              ? { items: [item(1, { version: 'v1b', result_data: { n: 9 } })], next_cursor: null }
              : { items: [] },
          ),
          { status: 200 },
        );
      }),
    );
    await press(window, { key: 'a' });
    await act(async () => {});
    expect(view.host.textContent).toContain('9');
    await view.unmount();
  });

  it('a free-text prompt is corrected with a text box', async () => {
    const free = item(1, { output_schema: null, result_data: null, result_text: 'hello' });
    const { view, calls } = await open({
      [LIST]: { items: [free], next_cursor: null },
      [reviewed(1)]: { item: free },
    });
    await press(window, { key: 'e' });
    const box = view.find<HTMLTextAreaElement>('[data-testid="images-review-text"]');
    expect(box?.value).toBe('hello');
    await setValue(box as HTMLTextAreaElement, 'hi');
    await click(view.find('[data-testid="images-review-save"]'));
    await act(async () => {});
    expect(posts(calls)).toEqual([{ action: 'correct', version: 'v1', data: { text: 'hi' } }]);
    await view.unmount();
  });

  it('an unusable schema falls back to JSON', async () => {
    const odd = item(1, { output_schema: { type: 'object', properties: { x: { type: 'object' } } } });
    const { view } = await open({ [LIST]: { items: [odd], next_cursor: null } });
    await press(window, { key: 'e' });
    expect(view.find('[data-testid="images-review-text"]')).not.toBeNull();
    await setValue(view.find('[data-testid="images-review-text"]') as HTMLTextAreaElement, '{nope');
    await click(view.find('[data-testid="images-review-save"]'));
    expect(view.host.textContent).toContain('not valid JSON');
    await view.unmount();
  });
});
