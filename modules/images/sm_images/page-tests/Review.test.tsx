// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, click, mount, press, setValue } from '../test-dom';
import { collection, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const Review = (await import('../pages/Review')).default;

const SCHEMA = {
  type: 'object',
  properties: { n: { type: 'integer' }, kind: { type: 'string', enum: ['a', 'b'] } },
  required: ['n'],
};

function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    prompt_id: 'p1',
    image_id: `i${id}`,
    group_id: null,
    status: 'completed',
    result_text: null,
    result_data: { n: id, kind: 'a' },
    error: null,
    cross_check: null,
    stale: false,
    review_status: 'unreviewed',
    reviewed_data: null,
    version: `v${id}`,
    prompt_name: 'count',
    output_schema: SCHEMA,
    filename: `${id}.jpg`,
    thumb_url: null,
    group_key: null,
    output_visible: true,
    ...overrides,
  };
}

const LIST = 'GET /api/images/collections/c1/review';
const prompts = { 'GET /api/images/collections/c1/prompts': { items: [] } };
const reviewed = (id: number) => `POST /api/images/prompt-results/${id}/review`;

async function open(routes: Record<string, unknown>) {
  const calls = stubFetch({ ...prompts, ...routes });
  const view = await mount(<Review collection={collection()} />);
  await act(async () => {});
  return { view, calls };
}

const shown = (view: { find: (s: string) => HTMLElement | null }) =>
  view.find('[data-testid="images-review-panel"]')?.dataset.resultId;
const posts = (calls: { method: string; body: unknown }[]) =>
  calls.filter((c) => c.method === 'POST').map((c) => c.body);

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

  const many = Array.from({ length: 11 }, (_, n) => item(n + 1));
  const paged = (after: (u: string) => unknown) => ({
    [LIST]: (call: { url: string }) =>
      call.url.includes('after=') ? after(call.url) : { items: many, next_cursor: 11 },
  });

  it('tops the queue up from the next page, so it is never empty while more exist', async () => {
    const { view, calls } = await open({
      ...paged(() => ({ items: [item(12)], next_cursor: null })),
      ...Object.fromEntries(
        many.map((m) => [reviewed(m.id), { item: { ...m, review_status: 'accepted' } }]),
      ),
    });
    const loads = () => calls.filter((c) => c.url.includes('after=11')).length;
    await press(window, { key: 'a' });
    await act(async () => {});
    expect(loads()).toBe(0); // 10 are left
    await press(window, { key: 'a' });
    await act(async () => {});
    expect(loads()).toBe(1); // 9 are left and the server has more
    for (let n = 0; n < 9; n++) {
      expect(view.find('[data-testid="images-review-empty"]')).toBeNull();
      await press(window, { key: 'a' });
      await act(async () => {});
    }
    expect(shown(view)).toBe('12');
    await view.unmount();
  });

  it('shows a Load more button while the server has more', async () => {
    const { view, calls } = await open(paged(() => ({ items: [item(12)], next_cursor: null })));
    await click(view.find('[data-testid="images-review-more"]'));
    await act(async () => {});
    expect(calls.filter((c) => c.url.includes('after=11'))).toHaveLength(1);
    expect(view.find('[data-testid="images-review-more"]')).toBeNull();
    await view.unmount();
  });

  it('two quick j at the end read one page, with no duplicates', async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { view, calls } = await open(
      paged(() => ({ items: [item(11), item(12)], next_cursor: null })),
    );
    const routed = globalThis.fetch;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await routed(input, init);
      if (String(input).includes('after=')) await gate;
      return response;
    });
    for (let n = 0; n < 10; n++) await press(window, { key: 'j' });
    await press(window, { key: 'j' });
    await press(window, { key: 'j' });
    expect(calls.filter((c) => c.url.includes('after=11'))).toHaveLength(1);
    await act(async () => {
      (release as (() => void) | null)?.();
    });
    await act(async () => {});
    expect(view.find('[data-testid="images-review-position"]')?.textContent).toContain('of 12');
    await view.unmount();
  });

  it('shows the translated message of a refused correction', async () => {
    const { view } = await open({ [LIST]: { items: [item(1)], next_cursor: null } });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
        (init?.method ?? 'GET') === 'POST'
          ? new Response(JSON.stringify({ detail: 'n: bad', code: 'invalid_review_data' }), {
              status: 422,
            })
          : new Response('{}', { status: 200 }),
      ),
    );
    await press(window, { key: 'e' });
    await click(view.find('[data-testid="images-review-save"]'));
    await act(async () => {});
    expect(view.find('[data-testid="images-review-error"]')?.textContent).toContain(
      "does not match the prompt's output schema",
    );
    await view.unmount();
  });

  it('refuses a fraction in an integer field before sending', async () => {
    const { view, calls } = await open({ [LIST]: { items: [item(1)], next_cursor: null } });
    await press(window, { key: 'e' });
    await setValue(view.find('[data-testid="images-review-field-n"]') as HTMLInputElement, '1.5');
    await click(view.find('[data-testid="images-review-save"]'));
    expect(posts(calls)).toEqual([]);
    expect(view.host.textContent).toContain('whole number');
    await view.unmount();
  });
});
