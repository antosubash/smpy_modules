// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { flush } from '../../page-tests/support';
import { click, mount } from '../../test-dom';
import { PublicGallery } from './PublicGallery';

afterEach(() => vi.unstubAllGlobals());

const tile = (id: string) => ({
  id,
  width: 8,
  height: 8,
  thumb_url: `/t/${id}`,
  display_url: `/d/${id}`,
});

describe('PublicGallery load more', () => {
  it('aborts a pending page when the slug changes', async () => {
    const signals: { url: string; signal?: AbortSignal | null }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        signals.push({ url, signal: init?.signal });
        if (url.includes('cursor=more')) return new Promise(() => {}); // never answers
        return Promise.resolve(
          new Response(JSON.stringify({ items: [tile('a')], next_cursor: 'more' }), {
            status: 200,
          }),
        );
      }),
    );
    const view = await mount(<PublicGallery slug="one" name="One" />);
    await flush();
    await click(view.find('[data-testid="images-public-more"]'));
    const pending = signals.find((s) => s.url.includes('cursor=more'));
    expect(pending?.signal).toBeDefined();
    expect(pending?.signal?.aborted).toBe(false);
    await view.render(<PublicGallery slug="two" name="Two" />);
    expect(pending?.signal?.aborted).toBe(true);
    await view.unmount();
  });
});
