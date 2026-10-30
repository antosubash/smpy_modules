// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { act, click, press, setValue } from './test-dom';
import { item, LIST, open, posts, reviewed, shown } from './reviewSupport';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

describe('review queue paging', () => {
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

  it("a filter change never pages with the old filter's cursor", async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const ten = Array.from({ length: 10 }, (_, n) => item(n + 1));
    const { view, calls } = await open({
      [LIST]: (call: { url: string }) => {
        if (call.url.includes('status=accepted')) {
          return { items: [item(1001, { review_status: 'accepted' })], next_cursor: null };
        }
        return call.url.includes('after=')
          ? { items: [item(11)], next_cursor: null }
          : { items: ten, next_cursor: 10 };
      },
      [reviewed(1)]: { item: item(1, { review_status: 'accepted' }) },
    });
    const routed = globalThis.fetch;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await routed(input, init);
      if (String(input).includes('status=unreviewed') && String(input).includes('after=')) {
        await gate;
      }
      return response;
    });
    await press(window, { key: 'a' }); // 9 left: the top-up for after=10 is held
    await act(async () => {});
    const select = view.find('[data-testid="images-review-status-filter"]');
    await setValue(select as HTMLSelectElement, 'accepted');
    await act(async () => {});
    await act(async () => {
      (release as (() => void) | null)?.();
    });
    await act(async () => {});
    const mixed = calls.filter((c) => c.url.includes('status=accepted') && c.url.includes('after='));
    expect(mixed).toEqual([]);
    expect(shown(view)).toBe('1001');
    expect(view.find('[data-testid="images-review-position"]')?.textContent).toContain('of 1');
    await view.unmount();
  });
});
